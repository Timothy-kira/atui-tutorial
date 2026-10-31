"""Declarative UI from actual tool records; this module never writes chat."""
from . import surfaces

def present_result(result):
    kind=result.get('ui_request')
    if kind=='recommendation_filters':return surfaces.recommendations(result['recommendation'])
    if kind=='checkout':return surfaces.checkout(result['quote'])
    if kind=='cart':return surfaces.cart_view(result['cart'])
    if kind=='calorie_summary':return surfaces.calorie_summary(result['cart'],result['party_size'])
    if kind=='reservation_form':return surfaces.reservation_form(result['date'],result['start_time'],result['end_time'],result['party_size'])
    if kind=='reservation_availability':return surfaces.reservation_availability(result['availability'])
    if kind=='order_success':return surfaces.success(result['order'])
    if kind=='reservation_success':return surfaces.reservation_success(result['reservation'])
    if not result.get('render_ui'):return None
    if 'dishes' in result:
        return surfaces.menu_cards(result['dishes'][:6]) if result['dishes'] else None
    if 'preparation' in result and 'id' in result:return surfaces.dish_details(result)
    return None
