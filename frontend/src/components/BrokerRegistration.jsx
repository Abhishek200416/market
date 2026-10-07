import {Copy,Check,Download,ExternalLink,ShieldCheck} from 'lucide-react';
import {Badge} from './TerminalUI';
import {Button} from './ui/button';
import {toast} from './ui/sonner';

export const BrokerRegistration=({registration:r})=>{
 const copy=async value=>{try{await navigator.clipboard.writeText(value);toast.success('Copied.');}catch(e){toast.error('Clipboard unavailable. Select and copy the text.');}};
 const rows=[
  ['app-name','App name',r?.app_name||'EDGE INDIA Research','For your own developer app registration.',r?.app_name||'EDGE INDIA Research'],
  ['website','Website',r?.website_url||'Pending permanent HTTPS hostname','No preview URL is presented as a verified broker endpoint.',r?.website_url],
  ['redirect','Redirect URL',r?.callback_url||'Full URL pending',`GET ${r?.callback_path||'/api/integrations/upstox/oauth/callback'} · This route receives the login code, not order updates.`,r?.callback_url],
  ['postback','Postback URL','Not required for market data','No order-status receiver is enabled. Leave unset for this data-only setup if the broker permits.',null],
  ['primary-ip','Primary IP','Not verified / not reserved','Do not enter a website IP or select an arbitrary address from a shared outbound pool.',null],
  ['secondary-ip','Secondary IP','Not verified / not reserved','Confirm the exact token and API-category requirement with your broker before filling this field.',null],
 ];
 return <section className="registration-details" data-testid="broker-ip-callback-info">
  <div className="registration-title"><h2>Broker registration details</h2><Badge id="broker-registration-status" tone="amber">{r?.oauth_ready?'CONFIGURED · VERIFY WITH BROKER':'REGISTRATION PENDING'}</Badge></div>
  <p className="registration-description" data-testid="broker-registration-intro">These fields describe the Upstox connection. Paytm Money is a separate, later integration—do not reuse this callback or an Upstox token for Paytm.</p>
  {rows.map(([id,label,value,note,copyValue])=><div className="registration-row" key={id} data-testid={`broker-field-${id}`}><span>{label}</span><div><strong className={!copyValue?'pending':''}>{value}</strong><p>{note}</p></div>{copyValue?<button data-testid={`copy-broker-${id}`} className="icon-button" title={`Copy ${label}`} aria-label={`Copy ${label}`} onClick={()=>copy(copyValue)}><Copy size={17}/></button>:<span/>}</div>)}
  <div className="registration-row" data-testid="broker-field-description"><span>Description</span><div><strong>{r?.description||'Private Indian-market research and AI-model evaluation with simulated paper trading. Real-money execution disabled.'}</strong></div><button data-testid="copy-broker-description" className="icon-button" title="Copy description" aria-label="Copy app description" onClick={()=>copy(r?.description||'Private Indian-market research and AI-model evaluation with simulated paper trading. Real-money execution disabled.')}><Copy size={17}/></button></div>
  <div className="security-note" data-testid="upstox-static-ip-policy"><ShieldCheck size={19}/><span>Upstox’s Analytics Token documentation distinguishes market quotes/history from account and portfolio APIs. Quotes/history do not require a static IP under that documented token policy. Account permissions and broker rules still need verification.</span></div>
  <div className="broker-policy-links"><a className="connection-help-link" data-testid="upstox-analytics-docs" href="https://upstox.com/developer/api-documentation/analytics-token/" target="_blank" rel="noreferrer">Official Analytics Token policy <ExternalLink size={14}/></a><a className="connection-help-link" data-testid="upstox-oauth-docs" href="https://upstox.com/developer/api-documentation/authorize/" target="_blank" rel="noreferrer">Official callback requirements <ExternalLink size={14}/></a><Button asChild variant="outline" data-testid="download-app-logo"><a href="/edge-india-logo.png" download="edge-india-logo.png"><Download size={15}/> Download app logo (PNG)</a></Button></div>
 </section>;
};