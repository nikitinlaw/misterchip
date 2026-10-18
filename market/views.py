"""Market pages; all private objects are scoped to an owner or shop capability."""
import time
import uuid
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from . import services
from .forms import (
    InquiryForm, InquiryReplyForm, InquiryStatusForm, MembershipForm,
    MembershipUpdateForm, OfferConfirmationForm, OfferForm, SellerProfileForm, ShopForm,
    VisibilityForm,
)
from .models import Inquiry, Offer, SellerProfile, Shop, ShopMembership
from .permissions import (
    can_manage_inquiries, can_manage_memberships, can_manage_offers,
    can_manage_shop, inquiries_for_user, shops_for_user,
)
from .security import inquiry_rate_limit


NONCE_SESSION_KEY = "market_inquiry_submissions"
NONCE_TTL = 2 * 60 * 60
NONCE_LIMIT = 20


def _actor(request):
    user = request.user
    return user if user.is_authenticated and user.is_active else None


def _form_error(form, error):
    if hasattr(error, "message_dict"):
        for field, errors in error.message_dict.items():
            target = field if field in form.fields else None
            for message in errors:
                form.add_error(target, message)
    else:
        form.add_error(None, error)


def _shop_for(request, shop_id, *, capability=None):
    return get_object_or_404(
        shops_for_user(request.user, capability=capability).select_related("seller__user"),
        pk=shop_id,
    )


def _offer_for(request, offer_id):
    return get_object_or_404(
        Offer.objects.select_related("shop__seller__user", "product").filter(
            shop__in=shops_for_user(request.user, capability="offers"),
        ), pk=offer_id,
    )


def _save_message(kind, record):
    if record.status == "published":
        return f"{kind}: сведения обновлены."
    if record.status == "pending":
        return f"{kind}: изменения отправлены на проверку."
    return f"{kind}: черновик сохранён. Отправьте его на проверку, когда будете готовы."


def shop_list(request):
    shops = Shop.objects.public().select_related("seller").order_by("name", "pk")
    return render(request, "market/shop_list.html", {
        "page": Paginator(shops, 12).get_page(request.GET.get("page")),
    })


def shop_detail(request, slug):
    shop = get_object_or_404(Shop.objects.public().select_related("seller"), slug=slug)
    offers = Offer.objects.public().filter(shop=shop).select_related("product", "shop__seller__user")
    return render(request, "market/shop_detail.html", {
        "shop": shop, "page": Paginator(offers, 20).get_page(request.GET.get("page")),
    })


@never_cache
@login_required
def seller_dashboard(request):
    shops = shops_for_user(request.user).select_related("seller__user")
    cards = [{
        "shop": shop,
        "can_offers": can_manage_offers(request.user, shop),
        "can_inquiries": can_manage_inquiries(request.user, shop),
    } for shop in shops]
    seller = SellerProfile.objects.filter(user=request.user).first()
    return render(request, "market/seller_dashboard.html", {"cards": cards, "seller": seller})


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def seller_profile(request):
    seller = SellerProfile.objects.filter(user=request.user).first()
    form = SellerProfileForm(request.POST if request.method == "POST" else None, instance=seller)
    if request.method == "POST" and form.is_valid():
        try:
            saved = services.save_seller_profile(actor=request.user, data=form.cleaned_data)
        except ValidationError as error:
            _form_error(form, error)
        else:
            messages.success(request, "Сведения продавца сохранены." if saved.status == SellerProfile.Status.VERIFIED else "Сведения продавца отправлены на проверку.")
            return redirect("market_seller_dashboard")
    return render(request, "market/seller_profile.html", {"form": form, "seller": seller})


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def shop_create(request):
    seller = SellerProfile.objects.filter(user=request.user).first()
    if seller is None:
        messages.info(request, "Сначала заполните сведения продавца.")
        return redirect("market_seller_profile")
    form = ShopForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            shop = services.save_shop(actor=request.user, data=form.cleaned_data)
        except ValidationError as error:
            _form_error(form, error)
        else:
            messages.success(request, _save_message("Магазин", shop))
            return redirect("market_shop_dashboard", shop_id=shop.pk)
    return render(request, "market/shop_form.html", {"form": form, "shop": None, "seller": seller})


@never_cache
@login_required
def shop_dashboard(request, shop_id):
    shop = _shop_for(request, shop_id)
    manage_offers = can_manage_offers(request.user, shop)
    manage_inquiries = can_manage_inquiries(request.user, shop)
    offers = shop.offers.select_related("product").order_by("-updated_at", "-pk") if manage_offers else Offer.objects.none()
    inquiries = shop.inquiries.select_related("offer__product").order_by("-created_at", "-pk") if manage_inquiries else Inquiry.objects.none()
    offers_page = Paginator(offers, 20).get_page(request.GET.get("offers_page"))
    inquiries_page = Paginator(inquiries, 20).get_page(request.GET.get("inquiries_page"))
    return render(request, "market/shop_dashboard.html", {
        "shop": shop, "can_edit": can_manage_shop(request.user, shop),
        "can_members": can_manage_memberships(request.user, shop),
        "can_offers": manage_offers, "can_inquiries": manage_inquiries,
        "offers": offers_page, "inquiries": inquiries_page,
        "offers_pagination_prefix": f"inquiries_page={inquiries_page.number}",
        "inquiries_pagination_prefix": f"offers_page={offers_page.number}",
    })


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def shop_edit(request, shop_id):
    shop = _shop_for(request, shop_id, capability="shop")
    form = ShopForm(request.POST if request.method == "POST" else None, instance=shop)
    if request.method == "POST" and form.is_valid():
        try:
            # ModelForm validation mutates its instance; compare against a fresh record.
            fresh_shop = _shop_for(request, shop_id, capability="shop")
            saved = services.save_shop(actor=request.user, data=form.cleaned_data, shop=fresh_shop)
        except ValidationError as error:
            _form_error(form, error)
        else:
            messages.success(request, _save_message("Магазин", saved))
            return redirect("market_shop_dashboard", shop_id=shop.pk)
    return render(request, "market/shop_form.html", {"form": form, "shop": shop})


@never_cache
@login_required
@require_POST
def shop_submit(request, shop_id):
    shop = _shop_for(request, shop_id, capability="shop")
    try:
        services.submit_shop(actor=request.user, shop=shop)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, "Магазин отправлен на проверку.")
    return redirect("market_shop_dashboard", shop_id=shop.pk)


@never_cache
@login_required
@require_POST
def shop_visibility(request, shop_id):
    shop = _shop_for(request, shop_id, capability="shop")
    form = VisibilityForm(request.POST)
    if form.is_valid():
        try:
            saved = services.set_shop_status(actor=request.user, shop=shop, status=form.cleaned_data["status"])
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, f"Магазин: {saved.get_status_display().lower()}.")
    else:
        messages.error(request, "Выберите доступное действие для магазина.")
    return redirect("market_shop_dashboard", shop_id=shop.pk)


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def shop_members(request, shop_id):
    shop = _shop_for(request, shop_id, capability="memberships")
    form = MembershipForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            services.save_membership(
                actor=request.user, shop=shop, user=form.target_user,
                role=form.cleaned_data["role"], is_active=True,
            )
        except ValidationError as error:
            _form_error(form, error)
        else:
            messages.success(request, "Доступ сотрудника сохранён.")
            return redirect("market_shop_members", shop_id=shop.pk)
    members = shop.memberships.select_related("user").order_by("user__username", "pk")
    return render(request, "market/shop_members.html", {
        "shop": shop, "form": form,
        "members": [{"member": member, "form": MembershipUpdateForm(instance=member, auto_id=f"member_{member.pk}_%s")} for member in members],
    })


@never_cache
@login_required
@require_POST
def membership_update(request, shop_id, member_id):
    shop = _shop_for(request, shop_id, capability="memberships")
    member = get_object_or_404(ShopMembership.objects.select_related("user"), shop=shop, pk=member_id)
    form = MembershipUpdateForm(request.POST, instance=member, auto_id=f"member_{member.pk}_%s")
    if form.is_valid():
        try:
            services.save_membership(
                actor=request.user, shop=shop, user=member.user,
                role=form.cleaned_data["role"], is_active=form.cleaned_data["is_active"],
            )
        except ValidationError as error:
            _form_error(form, error)
        else:
            messages.success(request, "Права сотрудника обновлены.")
            return redirect("market_shop_members", shop_id=shop.pk)
    return render(request, "market/membership_form.html", {"shop": shop, "member": member, "form": form})


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def offer_create(request, shop_id):
    shop = _shop_for(request, shop_id, capability="offers")
    form = OfferForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            offer = services.save_offer(actor=request.user, shop=shop, data=form.cleaned_data)
        except ValidationError as error:
            _form_error(form, error)
        else:
            messages.success(request, _save_message("Предложение", offer))
            return redirect("market_shop_dashboard", shop_id=shop.pk)
    return render(request, "market/offer_form.html", {"shop": shop, "offer": None, "form": form})


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def offer_edit(request, offer_id):
    offer = _offer_for(request, offer_id)
    shop = offer.shop
    form = OfferForm(request.POST if request.method == "POST" else None, instance=offer)
    if request.method == "POST" and form.is_valid():
        try:
            saved = services.save_offer(
                actor=request.user, shop=shop, offer=_offer_for(request, offer_id), data=form.cleaned_data,
            )
        except ValidationError as error:
            _form_error(form, error)
        else:
            messages.success(request, _save_message("Предложение", saved))
            return redirect("market_shop_dashboard", shop_id=shop.pk)
    return render(request, "market/offer_form.html", {"shop": shop, "offer": offer, "form": form})


@never_cache
@login_required
@require_POST
def offer_submit(request, offer_id):
    offer = _offer_for(request, offer_id)
    try:
        services.submit_offer(actor=request.user, offer=offer)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, "Предложение отправлено на проверку.")
    return redirect("market_shop_dashboard", shop_id=offer.shop_id)


@never_cache
@login_required
@require_POST
def offer_visibility(request, offer_id):
    offer = _offer_for(request, offer_id)
    form = VisibilityForm(request.POST)
    if form.is_valid():
        try:
            saved = services.set_offer_status(actor=request.user, offer=offer, status=form.cleaned_data["status"])
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, f"Предложение: {saved.get_status_display().lower()}.")
    else:
        messages.error(request, "Выберите доступное действие для предложения.")
    return redirect("market_shop_dashboard", shop_id=offer.shop_id)


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def offer_confirm(request, offer_id):
    offer = _offer_for(request, offer_id)
    initial_until = offer.valid_until if offer.valid_until and offer.valid_until > timezone.now() else timezone.now() + timedelta(days=7)
    form = OfferConfirmationForm(
        request.POST if request.method == "POST" else None,
        initial={"valid_until": initial_until},
    )
    if request.method == "POST" and form.is_valid():
        try:
            services.confirm_offer(actor=request.user, offer=offer, valid_until=form.cleaned_data["valid_until"])
        except ValidationError as error:
            _form_error(form, error)
        else:
            messages.success(request, "Цена и наличие подтверждены.")
            return redirect("market_shop_dashboard", shop_id=offer.shop_id)
    return render(request, "market/offer_confirm.html", {"offer": offer, "shop": offer.shop, "form": form})


def _nonces(request):
    stored = request.session.get(NONCE_SESSION_KEY, {})
    if not isinstance(stored, dict):
        return {}
    now = time.time()
    valid = {}
    for key, entry in stored.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("created"), (int, float)):
            continue
        if 0 <= now - entry["created"] <= NONCE_TTL:
            valid[key] = entry
    return valid


def _issue_nonce(request, offer, actor):
    entries = _nonces(request)
    entries = dict(sorted(entries.items(), key=lambda item: item[1]["created"])[-(NONCE_LIMIT - 1):])
    key = str(uuid.uuid4())
    entries[key] = {
        "offer": offer.pk, "buyer": actor.pk if actor else None,
        "created": time.time(), "receipt": None,
    }
    request.session[NONCE_SESSION_KEY] = entries
    return key


@never_cache
@require_http_methods(["GET", "POST"])
@inquiry_rate_limit
def inquiry_create(request, offer_id):
    offer = get_object_or_404(
        Offer.objects.public().select_related("product", "shop__seller__user"), pk=offer_id,
    )
    actor = _actor(request)
    if request.method == "GET":
        form = InquiryForm(actor=actor, submission_key=_issue_nonce(request, offer, actor))
    else:
        form = InquiryForm(request.POST, actor=actor)
        if form.is_valid():
            key = str(form.cleaned_data["submission_key"])
            entries = _nonces(request)
            entry = entries.get(key)
            if entry is None or entry.get("offer") != offer.pk or entry.get("buyer") != (actor.pk if actor else None):
                form.add_error(None, "Срок отправки формы истёк. Откройте форму заново и повторите отправку.")
            elif entry.get("receipt"):
                return redirect("market_inquiry_received", public_id=entry["receipt"])
            else:
                try:
                    inquiry = services.create_inquiry(
                        offer=offer, actor=actor, data={
                            field: form.cleaned_data[field] for field in ("name", "email", "phone", "message")
                        }, consent=form.cleaned_data["consent"], submission_key=form.cleaned_data["submission_key"],
                    )
                except ValidationError as error:
                    _form_error(form, error)
                else:
                    entry["receipt"] = str(inquiry.public_id)
                    entries[key] = entry
                    request.session[NONCE_SESSION_KEY] = entries
                    return redirect("market_inquiry_received", public_id=inquiry.public_id)
    return render(request, "market/inquiry_form.html", {"offer": offer, "shop": offer.shop, "form": form})


@never_cache
def inquiry_received(request, public_id):
    identifier = str(public_id)
    actor = _actor(request)
    has_receipt = any(entry.get("receipt") == identifier for entry in _nonces(request).values())
    own_inquiry = actor is not None and Inquiry.objects.filter(public_id=public_id, buyer=actor).exists()
    if not has_receipt and not own_inquiry:
        raise Http404
    return render(request, "market/inquiry_received.html", {"public_id": identifier, "own_inquiry": own_inquiry})


@never_cache
@login_required
def my_inquiries(request):
    inquiries = inquiries_for_user(request.user).filter(buyer=request.user).select_related("shop", "offer__product")
    return render(request, "market/my_inquiries.html", {
        "page": Paginator(inquiries, 20).get_page(request.GET.get("page")),
    })


@never_cache
@login_required
def inquiry_detail(request, public_id):
    inquiry = get_object_or_404(
        inquiries_for_user(request.user).filter(buyer=request.user).select_related("shop", "offer__product"),
        public_id=public_id,
    )
    return render(request, "market/inquiry_detail.html", {"inquiry": inquiry})


@never_cache
@login_required
@require_POST
def inquiry_cancel(request, public_id):
    inquiry = get_object_or_404(Inquiry, public_id=public_id, buyer=request.user)
    try:
        services.set_inquiry_status(actor=request.user, inquiry=inquiry, status=Inquiry.Status.CANCELLED)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, "Обращение отменено.")
    return redirect("market_inquiry_detail", public_id=inquiry.public_id)


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def seller_inquiry_detail(request, public_id):
    inquiry = get_object_or_404(
        inquiries_for_user(request.user).filter(
            shop__in=shops_for_user(request.user, capability="inquiries"),
        ).select_related("shop__seller__user", "offer__product"),
        public_id=public_id,
    )
    action = request.POST.get("action") if request.method == "POST" else None
    reply_form = InquiryReplyForm(request.POST if action == "reply" else None)
    status_form = InquiryStatusForm(
        request.POST if action == "status" else None, initial={"status": inquiry.status},
    )
    transitions = services.INQUIRY_TRANSITIONS.get(inquiry.status, set())
    status_form.fields["status"].choices = [
        choice for choice in status_form.fields["status"].choices
        if choice[0] in transitions or choice[0] == inquiry.status
    ]
    if request.method == "POST":
        if action == "reply" and reply_form.is_valid():
            try:
                services.reply_to_inquiry(actor=request.user, inquiry=inquiry, text=reply_form.cleaned_data["reply_text"])
            except ValidationError as error:
                _form_error(reply_form, error)
            else:
                messages.success(request, "Ответ покупателю сохранён.")
                return redirect("market_seller_inquiry_detail", public_id=inquiry.public_id)
        elif action == "status" and status_form.is_valid():
            try:
                services.set_inquiry_status(actor=request.user, inquiry=inquiry, status=status_form.cleaned_data["status"])
            except ValidationError as error:
                _form_error(status_form, error)
            else:
                messages.success(request, "Статус обращения изменён.")
                return redirect("market_seller_inquiry_detail", public_id=inquiry.public_id)
        elif action not in ("reply", "status"):
            status_form.add_error(None, "Выберите действие для обращения.")
    return render(request, "market/seller_inquiry_detail.html", {
        "inquiry": inquiry, "reply_form": reply_form, "status_form": status_form,
    })
