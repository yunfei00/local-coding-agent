// Conservative metadata only: never forward raw arguments, stdout or error strings.
type Data=Record<string,unknown>;
export function summarizeToolEvent(type:string,data:Data){
 const safeId=(value:unknown)=>typeof value==="string"&&/^[a-zA-Z0-9_.:-]{1,128}$/.test(value)?value:undefined;
 const callId=safeId(data.callID??data.toolCallID);
 const name=safeId(data.toolName??data.tool);
 const input=data.input??data.arguments;
 const output=data.output??data.result;
 const error=data.error;
 const describe=(value:unknown):string|undefined=>{
  if(value===undefined)return undefined;
  if(value===null)return "空值";
  if(typeof value==="string")return "文本（"+value.length+" 字符，内容未公开）";
  if(Array.isArray(value))return "数组（"+value.length+" 项，内容未公开）";
  if(typeof value==="object")return "结构化数据（内容未公开）";
  return "标量（内容未公开）";
 };
 return {type,callId,name,input:describe(input),output:describe(output),error:error===undefined?undefined:"工具返回错误（详细内容未公开）"};
}
