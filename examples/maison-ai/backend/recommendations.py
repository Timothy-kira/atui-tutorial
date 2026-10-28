"""Validated recommendation filters and portions, from the actual menu fixture."""
import math
from .store import MENU,BusinessError

ALLERGENS=sorted({allergen for dish in MENU for allergen in dish['allergens']})
ALIASES={'dairy':'milk','eggs':'egg','wheat':'gluten','peanut':'nuts','peanuts':'nuts','tree-nuts':'nuts','tree nuts':'nuts','nut':'nuts'}

def candidates(party_size=2,dietary_preferences=None,budget=0,max_calories=0,excluded_allergens=None):
    if type(party_size) is not int or not 1<=party_size<=12:raise BusinessError('Choose 1–12 diners')
    if isinstance(budget,bool) or not isinstance(budget,(float,int)) or not math.isfinite(budget) or budget<0:raise BusinessError('Budget must be a non-negative amount')
    if type(max_calories) is not int or max_calories<0:raise BusinessError('Calorie limit must be a non-negative integer')
    diets=[];excluded=[]
    for allergen in excluded_allergens or []:
        if not isinstance(allergen,str):raise BusinessError('Invalid allergen filter')
        value=ALIASES.get(allergen.strip().lower(),allergen.strip().lower())
        if value not in ALLERGENS:raise BusinessError('Unknown allergen: '+value)
        if value not in excluded:excluded.append(value)
    for preference in dietary_preferences or []:
        if not isinstance(preference,str):raise BusinessError('Invalid dietary preference')
        value=preference.strip().lower()
        if value in ('vegan','vegetarian'):
            if value not in diets:diets.append(value)
        elif value.startswith('no-'):
            value=ALIASES.get(value[3:],value[3:])
            if value not in ALLERGENS:raise BusinessError('Unknown allergen: '+value)
            if value not in excluded:excluded.append(value)
        else:raise BusinessError('Unsupported dietary preference: '+value)
    matches=[]
    for dish in MENU:
        if not dish['available'] or any(not dish[diet] for diet in diets):continue
        if set(excluded).intersection(dish['allergens']):continue
        quantity=math.ceil(party_size/max(1,dish['servings']['people']))
        price=round(dish['price']*100)*quantity
        calories=dish['calories_kcal']*quantity
        if budget and price>round(budget*100):continue
        if max_calories and calories>max_calories*party_size:continue
        matches.append({**dish,'recommended_quantity':quantity,'group_price_cents':price,'group_calories_kcal':calories,'calories_per_person':round(calories/party_size)})
    rank={'main':0,'pasta_pizza':1,'appetizer':2,'dessert':3,'drink':4}
    matches.sort(key=lambda dish:(rank.get(dish['category'],5),dish['price']))
    matches=matches[:3]
    return {'party_size':party_size,'dietary_preferences':diets,'budget':budget,'max_calories':max_calories,'excluded_allergens':excluded,'allergen_options':ALLERGENS,'candidates':matches,'source':'backend/data/menu.json','currency':'SGD','calorie_limit_basis':'Estimated kcal per person for each dish, at the suggested quantity. This is not a complete-meal limit.','budget_basis':'Total price for the suggested portions of each candidate, not the sum of all candidates.'}
