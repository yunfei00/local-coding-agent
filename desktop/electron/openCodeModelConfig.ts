// P2 configuration builder. Only a separately authorized local gateway may be used.
export type LocalModelProfile = {
  model: string;
  context: number;
  maxOutput: number;
};
export function buildLocalModelConfig(profile: LocalModelProfile, gateway: {port:number; token:string},allowTools=false) {
  if (!/^[a-zA-Z0-9][a-zA-Z0-9_.:/-]{0,127}$/.test(profile.model)) throw new Error("Invalid model ID");
  if (!Number.isSafeInteger(profile.context) || profile.context < 1024 || profile.context > 262144 ||
      !Number.isSafeInteger(profile.maxOutput) || profile.maxOutput < 1 || profile.maxOutput >= profile.context) throw new Error("Invalid model limits");
  if (!Number.isSafeInteger(gateway.port) || gateway.port < 1 || gateway.port > 65535 ||
      !/^[a-f0-9]{64}$/.test(gateway.token)) throw new Error("Invalid local gateway");
  const provider = "lca-ollama";
  return {
    policies:[{action:"provider.use",resource:"*",effect:"deny"},{action:"provider.use",resource:provider,effect:"allow"}],
    model:provider+"/"+profile.model,
    providers:{[provider]:{
      package:"@opencode/ai/providers/openai-compatible",
      settings:{baseURL:"http://127.0.0.1:"+gateway.port+"/v1",apiKey:gateway.token},
      models:{[profile.model]:{name:profile.model,capabilities:{tools:allowTools},limit:{context:profile.context,output:profile.maxOutput}}}
    }}
  };
}
