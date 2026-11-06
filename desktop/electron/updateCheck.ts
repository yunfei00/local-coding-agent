import https from "node:https";

export type UpdateCheckResult = {
  ok: boolean;
  checked_at: string;
  current_version: string;
  latest_version?: string;
  update_available: boolean;
  release_url?: string;
  error?: string;
  automatic: false;
  can_auto_download: false;
  can_auto_install: false;
};

export type ReleaseMetadata = {
  tag_name?: string;
  html_url?: string;
  draft?: boolean;
  prerelease?: boolean;
  body?: string;
  assets?: {name:string;browser_download_url:string;size:number}[];
};

function numericParts(value: string): bigint[] | null {
  const normalized = value.trim().replace(/^v/i, "");
  const match = normalized.match(/^(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$/);
  if (!match) {
    return null;
  }
  return match.slice(1, 4).map((item) => BigInt(item));
}

export function compareVersions(left: string, right: string): number {
  const a = numericParts(left);
  const b = numericParts(right);
  if (!a || !b) {
    return left.localeCompare(right);
  }
  for (let index = 0; index < 3; index += 1) {
    if (a[index] !== b[index]) {
      return a[index] > b[index] ? 1 : -1;
    }
  }
  const pre=(v:string)=>v.trim().replace(/^v/i,'').split('+')[0].split('-').slice(1).join('-');
  const x=pre(left),y=pre(right);
  if(!x||!y)return x===y?0:x?-1:1;
  const xx=x.split('.'),yy=y.split('.');
  for(let i=0;i<Math.max(xx.length,yy.length);i++){
    if(xx[i]===yy[i])continue;
    if(xx[i]===undefined)return -1;if(yy[i]===undefined)return 1;
    const nx=/^\d+$/.test(xx[i]),ny=/^\d+$/.test(yy[i]);
    if(nx&&ny)return BigInt(xx[i])>BigInt(yy[i])?1:-1;
    if(nx!==ny)return nx?-1:1;
    return xx[i]>yy[i]?1:-1;
  }
  return 0;
}

export function releaseResult(
  currentVersion: string,
  metadata: ReleaseMetadata
): UpdateCheckResult {
  const latest = String(metadata.tag_name ?? "").trim().replace(/^v/i, "");
  if (
    !latest ||
    metadata.draft === true ||
    metadata.prerelease === true
  ) {
    return {
      ok: false,
      checked_at: new Date().toISOString(),
      current_version: currentVersion,
      update_available: false,
      error: "Latest release metadata was not usable.",
      automatic: false,
      can_auto_download: false,
      can_auto_install: false
    };
  }

  return {
    ok: true,
    checked_at: new Date().toISOString(),
    current_version: currentVersion,
    latest_version: latest,
    update_available: compareVersions(latest, currentVersion) > 0,
    release_url:
      typeof metadata.html_url === "string" &&
      metadata.html_url.startsWith("https://github.com/")
        ? metadata.html_url
        : undefined,
    automatic: false,
    can_auto_download: false,
    can_auto_install: false
  };
}

export function requestJson(
  url: string,
  timeoutMs: number
): Promise<ReleaseMetadata> {
  return new Promise((resolve, reject) => {
    const request = https.get(
      url,
      {
        headers: {
          Accept: "application/vnd.github+json",
          "User-Agent": "local-coding-agent-update-check"
        }
      },
      (response) => {
        const status = response.statusCode ?? 0;
        let body = "";
        response.setEncoding("utf8");
        response.on("data", (chunk: string) => {
          body += chunk;
          if (body.length > 1_000_000) {
            request.destroy(new Error("Update response exceeded size limit."));
          }
        });
        response.on("end", () => {
          if (status < 200 || status >= 300) {
            reject(new Error("Update service returned HTTP " + status + "."));
            return;
          }
          try {
            resolve(JSON.parse(body) as ReleaseMetadata);
          } catch {
            reject(new Error("Update service returned invalid JSON."));
          }
        });
      }
    );

    request.setTimeout(timeoutMs, () => {
      request.destroy(new Error("Update check timed out."));
    });
    request.on("error", reject);
  });
}

export async function checkForUpdates(
  currentVersion: string,
  options: {
    url?: string;
    timeoutMs?: number;
  } = {}
): Promise<UpdateCheckResult> {
  const url =
    options.url ??
    "https://api.github.com/repos/yunfei00/local-coding-agent/releases/latest";
  const timeoutMs = options.timeoutMs ?? 5000;
  try {
    const metadata = await requestJson(url, timeoutMs);
    return releaseResult(currentVersion, metadata);
  } catch (error) {
    return {
      ok: false,
      checked_at: new Date().toISOString(),
      current_version: currentVersion,
      update_available: false,
      error: String(error instanceof Error ? error.message : error),
      automatic: false,
      can_auto_download: false,
      can_auto_install: false
    };
  }
}
