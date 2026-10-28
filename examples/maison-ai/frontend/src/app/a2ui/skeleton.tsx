'use client';
export function Skeleton({variant='line',failed=false}:{variant?:'line'|'body'|'card'|'cards';failed?:boolean}){
 if(failed)return <span className="stream-inline-error">Content could not load.</span>;
 if(variant==='cards')return <div className="dish-grid" aria-busy="true" aria-label="Loading dining options">{[0,1,2].map(id=><Skeleton key={id} variant="card"/>)}</div>;
 if(variant==='line')return <span className="a2ui-skeleton skeleton-line" aria-hidden="true"/>;
 const body=<><span className="a2ui-skeleton skeleton-photo"/><span className="a2ui-skeleton skeleton-line"/><span className="a2ui-skeleton skeleton-line skeleton-short"/><span className="a2ui-skeleton skeleton-action"/></>;
 return variant==='card'?<article className="dish-card skeleton-card" aria-busy="true" aria-label="Loading dish"><span className="a2ui-skeleton skeleton-title"/>{body}</article>:<div className="skeleton-body" aria-busy="true" aria-label="Loading details">{body}</div>;
}
