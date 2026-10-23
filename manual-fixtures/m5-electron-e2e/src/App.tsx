import {useEffect, useState} from 'react';
import {normalizeName} from './settings';
declare global { interface Window { fixture: {load:()=>Promise<string>;save:(value:string)=>Promise<string>} } }

export function App() {
  const [page,setPage]=useState('Home');
  const [draft,setDraft]=useState('');
  const [saved,setSaved]=useState('');
  const [status,setStatus]=useState('Not saved');
  useEffect(()=>{void window.fixture.load().then(value=>{setSaved(value);setDraft(value);});},[]);
  async function save() {
    const value=await window.fixture.save(normalizeName(draft));
    setSaved(value);
    setStatus('Not saved');
  }
  return <main style={{fontFamily:'Segoe UI, sans-serif',fontSize:18,padding:28}}>
    <nav><button onClick={()=>setPage('Home')}>Home</button> <button onClick={()=>setPage('Settings')}>Settings</button></nav>
    <h1>{page}</h1>
    {page==='Settings' ? <section>
      <label>Display name <input aria-label="Display name" disabled={true} value={draft} onChange={e=>setDraft(e.target.value)} /></label>
      <button onClick={()=>void save()}>Save</button>
      <p role="status" aria-label={'Status: '+status}>{status}</p>
    </section> : <p>Open Settings to update your display name.</p>}
    <p role="status" aria-label={'Persisted: '+saved}>{saved || 'No persisted value'}</p>
  </main>;
}
