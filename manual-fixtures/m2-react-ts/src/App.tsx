import {createRoot} from 'react-dom/client';
import {add} from './math.js';
const label: string = 123;
createRoot(document.getElementById('root')!).render(<h1>{label}: {add(3, 2)}</h1>);
