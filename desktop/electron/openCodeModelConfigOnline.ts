// Online profiles are metadata only until hard budget and transport gates pass.
export type OnlineModelProfile = {model:string; baseURL:string; credentialId:string};
export function validateOnlineModelProfile(profile:OnlineModelProfile):OnlineModelProfile {
  const url=new URL(profile.baseURL);
  if(url.protocol!=="https:" || url.username || url.password || url.search || url.hash) throw new Error("HTTPS provider URL required");
  if(!/^[a-zA-Z0-9][a-zA-Z0-9_.:/-]{0,127}$/.test(profile.model)) throw new Error("Invalid model ID");
  if(!/^[a-zA-Z0-9_-]{1,128}$/.test(profile.credentialId)) throw new Error("Invalid credential reference");
  return {model:profile.model,baseURL:url.href,credentialId:profile.credentialId};
}
export function activateOnlineProvider():never {
  throw new Error("Online OpenCode provider disabled: hard budget gate pending");
}
