'use client';
import React,{useEffect,useState} from 'react';
import type {CatalogRenderers} from '@copilotkit/a2ui-renderer';
import {definitions} from './definitions';
import {useDining,useSurface,useSurfaceLoad} from './context';
import {RecommendationFilters,ServingInfo,NutritionTotal,CalorieControls,ReservationForm,ReservationStatus} from './workflow-renderers';
import {Skeleton} from './skeleton';
export const money=(cents:number)=>new Intl.NumberFormat('en-SG',{style:'currency',currency:'SGD'}).format(cents/100);
const text=(v:unknown)=>typeof v==='string'?v:'';
function Photo({id}:{id:string}){const {menu}=useDining();const dish=menu.find(d=>d.id===id);return <PhotoAsset key={dish?.image||id} src={dish?.image||'/images/placeholder.svg'} name={dish?.name||'Dish'}/>;}
function PhotoAsset({src,name}:{src:string;name:string}){const [failed,setFailed]=useState(false),[loaded,setLoaded]=useState(false);return <div className="dish-photo streaming-photo">{!loaded&&<span className="a2ui-skeleton skeleton-photo" aria-hidden="true"/>}<img ref={image=>{if(image?.complete&&image.naturalWidth>0)setLoaded(true);}} className={loaded?'photo-ready':'photo-pending'} src={failed?'/images/placeholder.svg':src} alt={name} onLoad={()=>setLoaded(true)} onError={()=>{if(failed)setLoaded(true);else setFailed(true);}}/></div>;}

function Options({dishId,option,value}:{dishId:string;option:string;value:unknown}){const d=useDining();const surface=useSurface();const dish=d.menu.find(x=>x.id===dishId);const choices=dish?.options[option]||[];const selected=d.selections[dishId]?.options?.[option]||text(value)||(option==='doneness'?'':choices[0])||'';useEffect(()=>{if(selected)d.change(dishId,{options:{[option]:selected}},surface);},[dishId,option,surface]);return <label className="option-control"><span>{option==='doneness'?'How would you like it?':option==='side'?'Your side':'Milk'}</span><select aria-label={option} value={selected} onChange={e=>d.change(dishId,{options:{[option]:e.target.value}},surface)}>{option==='doneness'&&<option value="" disabled>Choose doneness</option>}{choices.map(c=><option key={c} value={c}>{c.replaceAll('-',' ')}</option>)}</select></label>;}
function Quantity({dishId,value}:{dishId:string;value:unknown}){const d=useDining();const surface=useSurface();const count=d.selections[dishId]?.quantity||(typeof value==='number'?value:1);return <div className="quantity-control"><span>Quantity</span><div><button aria-label="Decrease quantity" disabled={count<=1} onClick={()=>d.change(dishId,{quantity:count-1},surface)}>−</button><output>{count}</output><button aria-label="Increase quantity" disabled={count>=20} onClick={()=>d.change(dishId,{quantity:count+1},surface)}>+</button></div></div>;}
export const renderers:CatalogRenderers<typeof definitions>={
 Skeleton:({props})=><Skeleton variant={props.variant} failed={props.failed}/>,
 Row:({props,children})=><div className="dish-grid" style={{gap:props.gap??20}}>{props.children.map(id=><React.Fragment key={id}>{children(id)}</React.Fragment>)}</div>,
 Column:({props,children})=><div className="surface-column" style={{gap:props.gap??14}}>{props.children.map(id=><React.Fragment key={id}>{children(id)}</React.Fragment>)}</div>,
 Text:({props})=>{const state=useSurfaceLoad();return <p className="surface-copy">{text(props.text)||(state!=='ready'?<Skeleton failed={state==='failed'}/>:null)}</p>;},
 Card:({props,children})=>{const state=useSurfaceLoad();return <article className="dish-card"><h3>{text(props.title)||(state!=='ready'?<Skeleton failed={state==='failed'}/>:null)}</h3>{props.subtitle&&<p className="surface-copy">{text(props.subtitle)}</p>}{props.child&&children(props.child)}</article>;},
 Button:({props,dispatch})=>{const d=useDining(),state=useSurfaceLoad();const id=String(props.action.context?.dish_id||'');const dish=d.menu.find(item=>item.id===id);const needsChoice=props.action.name==='add_to_cart'&&(!dish||!!dish.options.doneness&&!d.selections[id]?.options?.doneness);return <button className="primary-button" disabled={d.busy||state!=='ready'||needsChoice||!text(props.label)} onClick={()=>dispatch?.(props.action)}>{text(props.label)||<Skeleton failed={state==='failed'}/>}</button>;},
 DishImage:({props})=><Photo id={props.dishId}/>,
 DishFacts:({props})=>{const dish=useDining().menu.find(x=>x.id===props.dishId);if(!dish)return null;return <section className="dish-facts"><h4>How it’s made</h4><p>{dish.preparation}</p><div className="dish-fact-grid"><div><span>Energy · estimate</span><strong>{dish.calories_kcal} kcal</strong></div><div><span>Serving</span><strong>{dish.servings.people} · {dish.servings.style}</strong><small>{dish.servings.note}</small></div></div><h4>Declared allergens</h4><p>{dish.allergens.length?dish.allergens.join(', '):'No major allergens declared in this demo recipe.'}</p><small>{dish.allergen_note} {dish.nutrition_basis}</small></section>;},
 PriceBadge:({props})=>{const d=useDining().menu.find(x=>x.id===props.dishId);return <span className="price-badge">{d?money(Math.round(d.price*100)):'Unavailable'}</span>;},
 DietaryBadge:({props})=><div className="dietary-tags">{props.vegan?<span>Plant-based</span>:props.vegetarian?<span>Vegetarian</span>:null}</div>,
 DishOptionSelector:({props})=><Options dishId={props.dishId} option={props.option} value={props.value}/>,
 QuantitySelector:({props})=><Quantity dishId={props.dishId} value={props.value}/>,
  CartItemControls:({props})=>{const d=useDining();const context={item_id:props.itemId,dish_id:props.dishId,options:props.options};return <div className="cart-stepper a2ui-cart-controls"><button aria-label={'Decrease '+props.dishId} disabled={d.busy} onClick={()=>d.send({name:'update_item',context:{...context,quantity:props.quantity-1}})}>−</button><output>{props.quantity}</output><button aria-label={'Increase '+props.dishId} disabled={d.busy||props.quantity>=20} onClick={()=>d.send({name:'update_item',context:{...context,quantity:props.quantity+1}})}>+</button><button className="remove-item" disabled={d.busy} onClick={()=>d.send({name:'remove_item',context})}>Remove</button></div>;},
 CartTotal:({props})=><div className="order-total"><span>Total</span><strong>{money(typeof props.totalCents==='number'?props.totalCents:0)}</strong></div>,
 OrderStatus:({props})=><div className="order-success"><span className="success-check">✓</span><h4>{text(props.status)}</h4><p>Order {text(props.orderId)}</p><strong>{money(typeof props.totalCents==='number'?props.totalCents:0)}</strong><p>This order is saved locally. No payment has been collected.</p></div>,
 RecommendationFilters:({props})=><RecommendationFilters {...props}/>,
 ServingInfo:({props})=><ServingInfo {...props}/>,
 NutritionTotal:({props})=><NutritionTotal {...props}/>,
 CalorieControls:({props})=><CalorieControls {...props}/>,
 ReservationForm:({props})=><ReservationForm {...props}/>,
 ReservationStatus:({props})=><ReservationStatus {...props}/>,
};
