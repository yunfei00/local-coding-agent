import type {ReactNode} from "react";
export type ToolEvent={type:string;callId?:string;name?:string;input?:string;output?:string;error?:string};
export type ToolCard=ToolEvent&{key:string;state:"running"|"succeeded"|"failed"|"unknown"};
export function appendToolEvent(cards:ToolCard[],event:ToolEvent):ToolCard[]{
 const state=event.type==="session.tool.success"?"succeeded":/\.(error|failed)$/.test(event.type)?"failed":/\.(call|start|started)$/.test(event.type)?"running":"unknown";
 const index=event.callId?cards.findIndex(card=>card.callId===event.callId):-1;
 if(index<0)return [...cards.slice(-99),{...event,key:event.callId||"event-"+(cards.length?Number(cards[cards.length-1].key.split("-").pop())+1:0),state}];
 return cards.map((card,i)=>i!==index?card:{...card,...Object.fromEntries(Object.entries(event).filter(([,v])=>v!==undefined)),state:card.state==="succeeded"||card.state==="failed"?card.state:state});
}
export function ToolExecutionCards({cards}:{cards:ToolCard[]}){
 const field=(label:string,value?:string):ReactNode=>value===undefined?null:<details><summary>{label}</summary><pre style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere",maxHeight:160,overflow:"auto"}}>{value}</pre></details>;
 return <section aria-label="工具执行记录">{cards.map((card,i)=><div key={card.key+":"+i} style={{border:"1px solid currentColor",borderRadius:6,padding:8,marginBottom:6}}><strong>{card.name||"未提供工具名称"}</strong> — {({running:"执行中",succeeded:"工具成功",failed:"工具失败",unknown:"状态未确认"})[card.state]}<div>{card.type}</div>{field("参数",card.input)}{field("结果",card.output)}{field("异常",card.error)}</div>)}</section>;
}
