import {execFile} from "node:child_process";
import {realpath} from "node:fs/promises";
import path from "node:path";
import {promisify} from "node:util";
const exec=promisify(execFile);
export type ProjectDiff={status:string;unstaged:string;staged:string};
export async function readProjectDiff(projectRoot:string,signal?:AbortSignal):Promise<ProjectDiff>{
 if(!path.isAbsolute(projectRoot))throw new Error("Invalid project path");
 const root=await realpath(projectRoot);
 const env=Object.fromEntries(Object.entries(process.env).filter(([key])=>!/^GIT_/i.test(key)));
 Object.assign(env,{GIT_OPTIONAL_LOCKS:"0",GIT_CONFIG_NOSYSTEM:"1",GIT_CONFIG_GLOBAL:process.platform==="win32"?"NUL":"/dev/null",GIT_TERMINAL_PROMPT:"0"});
 const git=async(args:string[])=> (await exec("git",["--no-pager","-c","core.fsmonitor=false","-c","core.quotePath=false",...args],{cwd:root,env,encoding:"utf8",timeout:10000,maxBuffer:1024*1024,windowsHide:true,signal})).stdout;
 const top=await realpath((await git(["rev-parse","--show-toplevel"])).trim());
 if(path.relative(root,top)!=="")throw new Error("Project must be the Git repository root");
 const options=["--no-ext-diff","--no-textconv","--no-color","--ignore-submodules=all"];
 const status=await git(["status","--short","--untracked-files=normal","--ignore-submodules=all"]);
 const unstaged=await git(["diff",...options,"--"]);
 const staged=await git(["diff","--cached",...options,"--"]);
 return {status,unstaged,staged};
}
