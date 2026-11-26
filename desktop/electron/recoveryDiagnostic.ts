import {acquireEngineLease} from "./engineLease";
import {resolveRecoveryStorage} from "./recoveryStorage";
import {inspectOriginalSession} from "./openCodeRecovery";
import {OpenCodeSupervisor} from "./openCodeSupervisor";
import type {HistoryEntry} from "./openCodeHistory";
export async function diagnoseHistorySession(input:{binary:string;userData:string;dataDir:string;entry:Pick<HistoryEntry,"sessionId"|"storageId"> & {status:string}}){
 const {entry}=input;
 if(["running","waiting","stopping"].includes(entry.status)||!entry.sessionId||!entry.storageId)throw new Error("History session is not eligible for diagnosis");
 const release=await acquireEngineLease(input.dataDir);
 const supervisor=new OpenCodeSupervisor();
 try{
  const root=await resolveRecoveryStorage(input.userData,entry.storageId);
  await supervisor.start(input.binary,root);
  return await inspectOriginalSession(supervisor,entry.sessionId);
 }finally{
  // Retain the lease if process cleanup cannot be confirmed.
  await supervisor.stop();
  await release();
 }
}
