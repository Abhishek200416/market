import {useState,useEffect,useCallback} from 'react';
import {useSearchParams} from 'react-router-dom';
import {LockKeyhole,ShieldCheck,Plug,Trash2,LoaderCircle,Sparkles,ExternalLink,ArrowUpRight,KeyRound} from 'lucide-react';
import {Button} from '../components/ui/button';
import {toast} from '../components/ui/sonner';
import {PageHeading,Badge} from '../components/TerminalUI';
import {BrokerRegistration} from '../components/BrokerRegistration';
import {api,errorText,formatTime} from '../lib/api';

const minorProviders=[{id:'gemini',title:'Gemini',sub:'Multi-agent intelligence',description:'The upstream TradingAgents team uses your Gemini key for research and debate. Risk checks stay independent of the AI.',fields:[['api_key','Gemini API key','Google AI Studio API key',true]]},{id:'fyers',title:'FYERS',sub:'Alternative market-data source',description:'An alternative read-only data connection. Select FYERS explicitly above to use it; no automatic provider switching occurs.',fields:[['client_id','Client ID','Your FYERS app ID',true],['access_token','Access token','Your FYERS access token',true],['secret','App secret (optional)','Your FYERS app secret',false]]}];

const ProviderStatus=({id,status})=><><div className="provider-status-line" data-testid={`${id}-last-success`}>LAST SUCCESSFUL REQUEST<br/>{formatTime(status?.last_success)}</div>{status?.error&&<div data-testid={`${id}-connection-error`} className="form-error" style={{marginTop:18}}>{status.error}</div>}</>;

export default function Connections({user,onAuth,onRefresh,overview}){
 const [rows,setRows]=useState([]),[values,setValues]=useState({upstox:{},fyers:{},gemini:{}}),[busy,setBusy]=useState('');
 const [registration,setRegistration]=useState(null),[params]=useSearchParams();
 const selected=overview?.market_provider||'upstox';
 const load=useCallback(()=>{if(user)api.get('/connections').then(r=>setRows(r.data.connections)).catch(e=>toast.error(errorText(e)));else setRows([]);},[user]);
 useEffect(()=>{load();api.get('/integrations/upstox/registration').then(r=>setRegistration(r.data)).catch(e=>toast.error(errorText(e)));},[load]);
 const status=id=>rows.find(r=>r.provider===id);
 const saved=(id,key)=>status(id)?.configured_fields?.includes(key);
 const change=(id,key,value)=>setValues(v=>({...v,[id]:{...v[id],[key]:value}}));
 const action=async(provider,type,part)=>{
  if(!user)return onAuth();setBusy(`${provider}-${type}`);
  try{
   let response;
   if(type==='save')response=await api.put(`/connections/${provider}`,{values:part||values[provider]});
   if(type==='test')response=await api.post(`/connections/${provider}/test`,null,{timeout:50000});
   if(type==='disconnect')response=await api.delete(`/connections/${provider}`);
   setRows(response.data.connections);setValues(v=>({...v,[provider]:{}}));onRefresh();
   if(type==='test')response.data.ok?toast.success('Read-only connection verified.'):toast.error('Connection failed. Review the provider message.');
   else toast.success(type==='save'?'Credentials encrypted and saved.':'Provider disconnected.');
  }catch(e){toast.error(errorText(e));}finally{setBusy('');}
 };
 const switchProvider=async provider=>{
  if(!user)return onAuth();setBusy('select');
  try{await api.put('/market-provider',{provider});onRefresh();toast.success(`Market data source changed to ${provider==='upstox'?'Upstox':'FYERS'}.`);}
  catch(e){toast.error(errorText(e));}finally{setBusy('');}
 };
 const authorize=async()=>{
  if(!user)return onAuth();setBusy('authorize');
  try{const {data}=await api.post('/integrations/upstox/oauth/start');window.location.assign(data.authorize_url);}
  catch(e){toast.error(errorText(e));setBusy('');}
 };
 const secretField=(id,key,label,placeholder,required=false)=><label key={key}>{label}{required?' *':''}<input data-testid={`${id}-${key.replaceAll('_','-')}`} type="password" autoComplete="off" maxLength={8192} placeholder={saved(id,key)?'Saved securely · enter to replace':placeholder} required={required&&!saved(id,key)} value={values[id][key]||''} onChange={e=>change(id,key,e.target.value)}/></label>;
 return <>
  <PageHeading eyebrow="SYSTEM / PROVIDERS" title="API connections" subtitle="Connect your data privately. Keep execution paper-only."><Badge tone="cyan" id="credential-security-badge">ENCRYPTED ON SERVER</Badge></PageHeading>
  {!user&&<div className="prerequisite-note" data-testid="connections-auth-notice">Sign in before saving a provider token. Chat credentials are not assigned to an account.<Button data-testid="connections-sign-in" variant="outline" onClick={onAuth}>Sign in <ArrowUpRight size={14}/></Button></div>}
  {params.get('authorization')==='complete'&&<div className="security-note" data-testid="upstox-authorization-complete"><ShieldCheck size={19}/>Upstox authorization completed. Test market data below before relying on the feed.</div>}
  <section className="provider-selector" data-testid="market-provider-selector"><div><h2>Active market-data source</h2><p>One explicit source for charts, research and paper fills. Switching is blocked while positions are open.</p></div><select data-testid="active-market-provider" aria-label="Active market-data source" value={selected} disabled={!!busy} onChange={e=>switchProvider(e.target.value)}><option value="upstox">Upstox</option><option value="fyers">FYERS</option></select></section>
  <div className="connection-grid">
   <section className="provider-card upstox-card" data-testid="upstox-connection-card">
    <div className="provider-title"><span className="provider-logo upstox">U</span><div><h2>Upstox</h2><p>Market quotes & completed candles <span className="connection-mode-tag">READ ONLY</span></p></div><Badge id="upstox-connection-status" tone={status('upstox')?.status==='CONNECTED'?'green':status('upstox')?.status==='ERROR'?'red':'muted'}>{status('upstox')?.status||'DISCONNECTED'}</Badge></div>
    <p className="provider-description">Start with an Analytics Token from your Upstox developer dashboard. Quotes and historical data are documented as available without a static IP for that token type. No order or account APIs are called.</p>
    <div className="upstox-fields">
     <form className="form-stack upstox-token-form" onSubmit={e=>{e.preventDefault();action('upstox','save',{access_token:values.upstox.access_token||''});}}>
      <h3>1. Connect market data</h3>
      {secretField('upstox','access_token','Analytics / access token','Paste a rotated read-only token',true)}
      <a data-testid="upstox-developer-dashboard" className="connection-help-link" href="https://account.upstox.com/developer/apps" target="_blank" rel="noreferrer">Open Upstox Developer Apps <ExternalLink size={14}/></a>
      <p className="field-hint" data-testid="upstox-token-instructions">In Upstox, open the Analytics tab and generate a token. An API key or app secret is not an access token.</p>
      <div className="provider-actions"><Button type="submit" disabled={!!busy} className="primary-button" data-testid="upstox-save-button"><LockKeyhole size={15}/>{busy==='upstox-save'?'Saving…':'Save token securely'}</Button><Button type="button" variant="outline" data-testid="upstox-test-button" disabled={!!busy||(!saved('upstox','access_token')&&!!user)} onClick={()=>action('upstox','test')}>{busy==='upstox-test'?<LoaderCircle className="spin"/>:<Plug size={15}/>} Test market data</Button>{status('upstox')?.configured_fields?.length>0&&<Button data-testid="upstox-disconnect-button" type="button" variant="ghost" size="icon" title="Disconnect and delete Upstox credentials" disabled={!!busy} onClick={()=>action('upstox','disconnect')}><Trash2 size={17}/></Button>}</div>
     </form>
     <form className="form-stack" onSubmit={e=>{e.preventDefault();action('upstox','save',{api_key:values.upstox.api_key||'',api_secret:values.upstox.api_secret||''});}}>
      <h3>2. Broker sign-in <span className="connection-mode-tag">OPTIONAL</span></h3>
      {secretField('upstox','api_key','Upstox API key','Your Upstox app API key',true)}
      {secretField('upstox','api_secret','Upstox API secret','Your rotated Upstox app secret',true)}
      <div className="provider-actions"><Button data-testid="upstox-save-app-button" type="submit" variant="outline" disabled={!!busy}><KeyRound size={15}/> Save app credentials</Button><Button data-testid="upstox-authorize-button" type="button" variant="outline" disabled={!!busy||!registration?.oauth_ready} onClick={authorize}><ArrowUpRight size={15}/> Sign in with Upstox</Button></div>
      <div className="oauth-pending-note" data-testid="upstox-oauth-gate"><LockKeyhole size={15}/><span>{registration?.oauth_ready?'Register the exact callback shown below with Upstox before signing in.':'Broker sign-in is pending a permanent HTTPS hostname. The token connection on the left does not need this callback.'}</span></div>
     </form>
    </div><ProviderStatus id="upstox" status={status('upstox')}/>
   </section>
   {minorProviders.map(p=><section className="provider-card" key={p.id} data-testid={`${p.id}-connection-card`}>
    <div className="provider-title"><span className={`provider-logo ${p.id}`}>{p.id==='fyers'?'F':<Sparkles size={24}/>}</span><div><h2>{p.title}</h2><p>{p.sub}</p></div><Badge id={`${p.id}-connection-status`} tone={status(p.id)?.status==='CONNECTED'?'green':status(p.id)?.status==='ERROR'?'red':'muted'}>{status(p.id)?.status||'DISCONNECTED'}</Badge></div>
    <p className="provider-description">{p.description}</p><form className="form-stack" onSubmit={e=>{e.preventDefault();action(p.id,'save');}}>{p.fields.map(([key,label,placeholder,required])=>secretField(p.id,key,label,placeholder,required))}<div className="provider-actions"><Button type="submit" disabled={!!busy} className="primary-button" data-testid={`${p.id}-save-button`}><LockKeyhole size={15}/> Save credentials</Button><Button type="button" variant="outline" disabled={!!busy||(!status(p.id)?.configured_fields?.length&&!!user)} onClick={()=>action(p.id,'test')} data-testid={`${p.id}-test-button`}>{busy===`${p.id}-test`?<LoaderCircle className="spin"/>:<Plug size={15}/>} Test connection</Button>{status(p.id)?.configured_fields?.length>0&&<Button type="button" variant="ghost" size="icon" data-testid={`${p.id}-disconnect-button`} title="Disconnect and delete credentials" onClick={()=>action(p.id,'disconnect')} disabled={!!busy}><Trash2 size={17}/></Button>}</div></form><ProviderStatus id={p.id} status={status(p.id)}/>
   </section>)}
  </div>
  <div className="security-note" data-testid="credential-security-note"><ShieldCheck size={19}/><span>Rotate credentials that were shared in chat. Store replacements here, not in another message. Secrets stay encrypted on the server and are never sent back to your browser.</span></div>
  <BrokerRegistration registration={registration}/>
 </>;
}