import {Copy,Check,Download,ExternalLink,ShieldCheck} from 'lucide-react';
import {Badge} from './TerminalUI';
import {Button} from './ui/button';
import {toast} from './ui/sonner';

export const BrokerRegistration=({registration:r})=>{
 const copy=async value=>{try{await navigator.clipboard.writeText(value);toast.success('Copied.');}catch(e){toast.error('Clipboard unavailable. Select and copy the text.');}};
 const currentOrigin=process.env.REACT_APP_BACKEND_URL?.replace(/\/$/,'');
 const website=r?.website_url||currentOrigin;
 const callback=r?.callback_url||(currentOrigin?`${currentOrigin}${r?.callback_path||'/api/integrations/upstox/oauth/callback'}`:null);
 const rows=[
  ['app-name','App name',r?.app_name||'EDGE INDIA Research','For your own developer app registration.',r?.app_name||'EDGE INDIA Research'],
  ['website','Website',website||'Loading app address',r?.oauth_ready?'Configured public website. Confirm it matches your broker application.':'Current preview address, filled from this app configuration. Use a permanent HTTPS domain for broker OAuth registration.',website],
  ['redirect','Redirect URL',callback||'Loading callback address',`GET callback · ${r?.oauth_ready?'Register this exact URL with Upstox.':'Preview reference only; OAuth stays disabled until a permanent domain is configured.'}`,callback],
  ['postback','Postback URL','Leave blank for market data','This app does not receive order updates. No postback is needed for the read-only Analytics Token flow.',null],
  ['primary-ip','Primary IP','Not required for Analytics Token','Market quotes/history only. No dedicated outbound IP is reserved. Do not use a website IP for account or trading APIs.',null],
  ['secondary-ip','Secondary IP','Not required for Analytics Token','If registering a different API category, obtain broker-approved static egress IPs from your hosting provider first.',null],
 ];
 return <section className="registration-details" data-testid="broker-ip-callback-info">
  <div className="registration-title"><h2>Broker registration details</h2><Badge id="broker-registration-status" tone="amber">{r?.oauth_ready?'CONFIGURED · VERIFY WITH BROKER':'TOKEN SETUP AVAILABLE'}</Badge></div>
  <div className="registration-summary" data-testid="broker-registration-help"><ShieldCheck size={20}/><span><b>The simplest route: paste an Upstox Analytics Token above.</b> No app login, callback or static IP is needed for this read-only data route. The fields below describe optional developer-app registration; preview URLs are references, not verified permanent broker endpoints.</span></div>
  <p className="registration-description" data-testid="broker-registration-intro">App details are filled below using the current configuration. Paytm Money is a separate, later integration—never reuse an Upstox token for Paytm.</p>
  {rows.map(([id,label,value,note,copyValue])=><div className="registration-row" key={id} data-testid={`broker-field-${id}`}><span>{label}</span><div><strong className={!copyValue?'pending':''}>{value}</strong><p>{note}</p></div>{copyValue?<button data-testid={`copy-broker-${id}`} className="icon-button" title={`Copy ${label}`} aria-label={`Copy ${label}`} onClick={()=>copy(copyValue)}><Copy size={17}/></button>:<span/>}</div>)}
  <div className="registration-row" data-testid="broker-field-description"><span>Description</span><div><strong>{r?.description||'Private Indian-market research and AI-model evaluation with simulated paper trading. Real-money execution disabled.'}</strong></div><button data-testid="copy-broker-description" className="icon-button" title="Copy description" aria-label="Copy app description" onClick={()=>copy(r?.description||'Private Indian-market research and AI-model evaluation with simulated paper trading. Real-money execution disabled.')}><Copy size={17}/></button></div>
  <div className="security-note" data-testid="upstox-static-ip-policy"><ShieldCheck size={19}/><span>Upstox’s Analytics Token documentation distinguishes market quotes/history from account and portfolio APIs. Quotes/history do not require a static IP under that documented token policy. Account permissions and broker rules still need verification.</span></div>
  <div className="broker-policy-links"><a className="connection-help-link" data-testid="upstox-analytics-docs" href="https://upstox.com/developer/api-documentation/analytics-token/" target="_blank" rel="noreferrer">Official Analytics Token policy <ExternalLink size={14}/></a><a className="connection-help-link" data-testid="upstox-oauth-docs" href="https://upstox.com/developer/api-documentation/authorize/" target="_blank" rel="noreferrer">Official callback requirements <ExternalLink size={14}/></a><Button asChild variant="outline" data-testid="download-app-logo"><a href="/edge-india-logo.png" download="edge-india-logo.png"><Download size={15}/> Download app logo (PNG)</a></Button></div>
 </section>;
};