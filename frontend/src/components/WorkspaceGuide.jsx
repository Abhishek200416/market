import {Link} from 'react-router-dom';
import {CheckCircle2,ArrowUpRight,Plug,Sparkles,ShieldCheck} from 'lucide-react';

export const WorkspaceGuide=({overview})=>{
 const connected=id=>overview?.connections?.some(row=>row.provider===id&&row.status==='CONNECTED');
 const broker=overview?.market_provider||'upstox';
 const steps=[
  ['workspace','Workspace ready','No account or password needed','/settings',true,CheckCircle2],
  ['market',`Connect ${broker==='upstox'?'Upstox':'FYERS'}`,'Your read-only market data','/connections',connected(broker),Plug],
  ['gemini','Connect Gemini','Your key, your research','/connections#gemini',connected('gemini'),Sparkles],
  ['research','Review AI signals','Fresh data and risk checks first','/signals',false,ShieldCheck]
 ];
 return <section className="workspace-guide" aria-label="Workspace setup" data-testid="workspace-guide"><div className="workspace-guide-heading"><h2>Your research, without the sign-up.</h2><span>Bring your own API keys</span></div><div className="workspace-steps">{steps.map(([id,title,description,path,done,Icon],index)=><Link key={id} data-testid={`setup-step-${id}`} to={path} className={`workspace-step ${done?'complete':''}`}><span className="step-number">{done?<CheckCircle2 size={19}/>:<Icon size={19}/>}</span><div><small>0{index+1} / {done?'READY':'NEXT STEP'}</small><b>{title}</b><p>{description}</p></div><ArrowUpRight size={15}/></Link>)}</div><p className="workspace-privacy">Separate workspace for this browser. Keys are encrypted on the server. Clearing cookies or 90 days of inactivity loses access; other browsers start separately.</p></section>;
};
