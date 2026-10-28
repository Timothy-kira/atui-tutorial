'use client';
import {useEffect,useState,type FormEvent} from 'react';
import {useDining} from './context';

type FilterProps={partySize:number;dietaryPreferences:string[];excludedAllergens:string[];allergenOptions:string[];maxCalories:number;budget:number};
export function RecommendationFilters(props:FilterProps){
 const d=useDining();
 const [party,setParty]=useState(props.partySize),[diet,setDiet]=useState(props.dietaryPreferences.includes('vegan')?'vegan':props.dietaryPreferences.includes('vegetarian')?'vegetarian':''),[allergens,setAllergens]=useState(props.excludedAllergens),[calories,setCalories]=useState(props.maxCalories||''),[budget,setBudget]=useState(props.budget||'');
 const key=JSON.stringify(props);
 useEffect(()=>{setParty(props.partySize);setDiet(props.dietaryPreferences.includes('vegan')?'vegan':props.dietaryPreferences.includes('vegetarian')?'vegetarian':'');setAllergens(props.excludedAllergens);setCalories(props.maxCalories||'');setBudget(props.budget||'');},[key]);
 function submit(e:FormEvent){e.preventDefault();d.send({name:'recommend_dishes',context:{party_size:party,dietary_preferences:diet?[diet]:[],excluded_allergens:allergens,max_calories:Number(calories)||0,budget:Number(budget)||0}});}
 return <form className="workflow-form recommendation-filters" onSubmit={submit}>
  <div className="workflow-title"><h3>Find dishes for your table</h3><p>Set your preferences and choose from matching dishes.</p></div>
  <fieldset disabled={d.busy}>
   <div className="workflow-fields"><label>Diners<input type="number" required min={1} max={12} value={party} onChange={e=>setParty(Number(e.target.value))}/></label><label>Diet<select value={diet} onChange={e=>setDiet(e.target.value)}><option value="">Any diet</option><option value="vegetarian">Vegetarian</option><option value="vegan">Vegan</option></select></label><label>Max kcal / person / dish<input type="number" min={0} max={10000} step={1} placeholder="No limit" value={calories} onChange={e=>setCalories(e.target.value===''?'':Number(e.target.value))}/></label><label>Max total / dish (S$)<input type="number" min={0} step="0.01" placeholder="No limit" value={budget} onChange={e=>setBudget(e.target.value===''?'':Number(e.target.value))}/></label></div>
   <div className="allergen-filter"><span>Exclude declared allergens</span><div>{props.allergenOptions.map(value=><label key={value}><input type="checkbox" checked={allergens.includes(value)} onChange={e=>setAllergens(current=>e.target.checked?[...current,value]:current.filter(item=>item!==value))}/><span>{value}</span></label>)}</div></div>
   <p className="workflow-note">Limits apply to each candidate at its suggested portions, not to a complete meal. Kitchen cross-contact information is unavailable.</p>
   <button className="primary-button" type="submit">{d.busy?'Finding dishes…':'Update recommendations'}</button>
  </fieldset>
 </form>;
}
export function ServingInfo({dishId,recommendedQuantity,partySize}:{dishId:string;recommendedQuantity:number;partySize:number}){
 const d=useDining(),dish=d.menu.find(item=>item.id===dishId);if(!dish)return null;
 const quantity=d.selections[dishId]?.quantity??recommendedQuantity;
 return <div className="serving-info"><strong>{quantity} {quantity===1?'portion':'portions'} · serves {quantity*dish.servings.people}</strong></div>;
}
export function NutritionTotal({totalKcal,partySize,showSplit}:{totalKcal:number;partySize:number;showSplit:boolean}){
 return <section className="nutrition-summary" aria-label="Calorie summary"><div><span>Total recipe energy</span><strong>{totalKcal.toLocaleString()} <small>kcal</small></strong></div>{showSplit&&<div><span>Equal split · {partySize} {partySize===1?'diner':'diners'}</span><strong>{Math.round(totalKcal/partySize).toLocaleString()} <small>kcal / person</small></strong></div>}<p>Estimated from menu recipes × portions. Customizations are not included.</p></section>;
}
export function CalorieControls({partySize}:{partySize:number}){
 const d=useDining();const [people,setPeople]=useState(partySize);useEffect(()=>setPeople(partySize),[partySize]);
 return <form className="calorie-controls" onSubmit={e=>{e.preventDefault();d.send({name:'calculate_calories',context:{party_size:people}});}}><label>Diners<input type="number" min={1} max={12} required value={people} onChange={e=>setPeople(Number(e.target.value))} disabled={d.busy}/></label><button className="primary-button" disabled={d.busy}>Recalculate</button></form>;
}
type ReservationProps={date:string;minDate:string;startTime:string;endTime:string;partySize:number};
export function ReservationForm(props:ReservationProps){
 const d=useDining();const [date,setDate]=useState(props.date),[from,setFrom]=useState(props.startTime),[to,setTo]=useState(props.endTime),[guests,setGuests]=useState(props.partySize);
 const key=JSON.stringify(props);useEffect(()=>{setDate(props.date);setFrom(props.startTime);setTo(props.endTime);setGuests(props.partySize);},[key]);
 return <form className="workflow-form reservation-form" onSubmit={e=>{e.preventDefault();d.send({name:'check_reservation',context:{date,start_time:from,end_time:to,party_size:guests}});}}><fieldset disabled={d.busy}><div className="workflow-fields"><label>Date<input type="date" min={props.minDate} required value={date} onChange={e=>setDate(e.target.value)}/></label><label>From<input type="time" required value={from} onChange={e=>setFrom(e.target.value)}/></label><label>To<input type="time" required value={to} onChange={e=>setTo(e.target.value)}/></label><label>Guests<input type="number" min={1} max={12} required value={guests} onChange={e=>setGuests(Number(e.target.value))}/></label></div><p className="workflow-note">Singapore restaurant time (UTC+08:00). Choose a table after checking availability.</p><button className="primary-button" type="submit">{d.busy?'Checking tables…':'Check available tables'}</button></fieldset></form>;
}
export function ReservationStatus(props:{reservationId:string;tableId:string;date:string;startTime:string;endTime:string;partySize:number;seats:number}){
 return <section className="reservation-confirmation"><span className="success-check">✓</span><h4>{props.date} · {props.startTime}–{props.endTime}</h4><p>{props.partySize} guests · Table {props.tableId} · {props.seats} seats</p><p>Singapore restaurant time (UTC+08:00)</p><strong>{props.reservationId}</strong><small>Saved locally for this demo. No external restaurant booking is made.</small></section>;
}
