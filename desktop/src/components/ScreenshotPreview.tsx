import {useState} from "react";

export function ScreenshotPreview({path}: {path: string}) {
  const [source, setSource] = useState("");
  const [error, setError] = useState("");
  return <div className="screenshot-preview">
    <button onClick={() => {if (source) {setSource(""); return;} setError(""); void window.localAgent.previewScreenshot(path).then(setSource).catch(cause => setError(String(cause)));}}>{source ? "Hide screenshot" : "View local screenshot"}</button>
    {error ? <p role="alert">{error}</p> : null}
    {source ? <img src={source} alt="Authorized local window capture, with privacy masking" style={{maxWidth:"100%",maxHeight:500,objectFit:"contain"}} /> : null}
  </div>;
}
