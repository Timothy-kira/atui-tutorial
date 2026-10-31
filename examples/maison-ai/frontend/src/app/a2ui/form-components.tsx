'use client';
import {createContext,useCallback,useContext,useEffect,useMemo,useState,type ReactNode} from 'react';
import {useDining,type UIAction} from './context';
type Value=string|number|boolean|string[];
const FormValues=createContext<{set:(name:string,value:Value)=>void}>({set:()=>{}});
export function ComposedForm({action,context,submitLabel,children}:{action:UIAction['name'];context:Record<string,unknown>;submitLabel:string;children:ReactNode}){
 const dining=useDining(),[fields,setFields]=useState<Record<string,Value>>({});
 const set=useCallback((name:string,value:Value)=>setFields(current=>({...current,[name]:value})),[]);
 const feed=useMemo(()=>({set}),[set]);
 return <FormValues.Provider value={feed}><form className="composed-form" onSubmit={event=>{event.preventDefault();void dining.send({name:action,context:{...context,...fields}});}}><fieldset disabled={dining.busy}><div className="composed-fields">{children}</div><button className="primary-button" type="submit">{dining.busy?'Updating…':submitLabel}</button></fieldset></form></FormValues.Provider>;
}
export function ComposedField({name,label,type,value,options=[],min,max,required=false}:{name:string;label:string;type:'text'|'number'|'date'|'time'|'select'|'multi';value:Value;options?:{label:string;value:string}[];min?:number;max?:number;required?:boolean}){
 const form=useContext(FormValues),[current,setCurrent]=useState<Value>(value);
 useEffect(()=>{setCurrent(value);form.set(name,value);},[name,JSON.stringify(value),form.set]);
 const change=(next:Value)=>{setCurrent(next);form.set(name,next);};
 if(type==='multi')return <fieldset className="composed-multi"><legend>{label}</legend><div>{options.map(option=><label key={option.value}><input type="checkbox" checked={Array.isArray(current)&&current.includes(option.value)} onChange={event=>{const values=Array.isArray(current)?current:[];change(event.target.checked?[...values,option.value]:values.filter(item=>item!==option.value));}}/>{option.label}</label>)}</div></fieldset>;
 return <label className="composed-field"><span>{label}</span>{type==='select'?<select value={String(current)} required={required} onChange={event=>change(event.target.value)}>{options.map(option=><option key={option.value} value={option.value}>{option.label}</option>)}</select>:<input type={type} value={Array.isArray(current)?'':String(current)} min={min} max={max} required={required} onChange={event=>change(type==='number'?(event.target.value===''?0:Number(event.target.value)):event.target.value)}/>}</label>;
}
