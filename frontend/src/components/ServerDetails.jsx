import {useCallback, useEffect, useState} from 'react';
import {Copy, Globe2, Inbox, LoaderCircle, RefreshCw, RotateCcw, Send, ShieldCheck} from 'lucide-react';
import {Button} from './ui/button';
import {Badge} from './TerminalUI';
import {toast} from './ui/sonner';
import {api, errorText, formatTime} from '../lib/api';
import './server-details.css';

const serverOrigin = process.env.REACT_APP_BACKEND_URL?.replace(/\/$/, '');

function DetailRow({id, label, value, note, copyValue}) {
 const copy = async () => {
  try { await navigator.clipboard.writeText(copyValue); toast.success(`${label} copied.`); }
  catch { toast.error('Clipboard unavailable. Select and copy the displayed text.'); }
 };
 return <div className="server-detail-row" data-testid={`server-field-${id}`}>
  <span className="server-detail-label">{label}</span>
  <div className="server-detail-value"><strong>{value}</strong><p>{note}</p></div>
  {copyValue && <button type="button" className="icon-button" onClick={copy} aria-label={`Copy ${label}`} title={`Copy ${label}`} data-testid={`copy-server-${id}`}><Copy size={17}/></button>}
 </div>;
}

export function ServerDetails({user}) {
 const [details, setDetails] = useState(null);
 const [receiver, setReceiver] = useState(null);
 const [events, setEvents] = useState([]);
 const [busy, setBusy] = useState('load');
 const [error, setError] = useState('');
 const [notice, setNotice] = useState('');
 const [confirmRotation, setConfirmRotation] = useState(false);
 const userId = user?.id;

 const load = useCallback(async () => {
  if (!userId) return;
  setBusy('load'); setError('');
  try {
   const [meta, endpoint, inbox] = await Promise.all([
    api.get('/server/connection-details'), api.post('/server/postback'), api.get('/server/events'),
   ]);
   setDetails(meta.data); setReceiver(endpoint.data); setEvents(inbox.data.events);
  } catch (e) { setError(errorText(e)); }
  finally { setBusy(''); }
 }, [userId]);
 useEffect(() => { load(); }, [load]);

 const postbackUrl = receiver && serverOrigin ? `${serverOrigin}${receiver.receive_path}` : null;
 const observation = details?.observation;
 const unavailable = error ? 'Unavailable — retry connection details' : 'Loading server details…';
 const ipValue = name => details ? (details[name] || 'Not assigned — no reserved address') : unavailable;
 const ipNote = name => details?.[name]
  ? 'Operator-configured value, not independently verified as reserved. Confirm routing with your hosting provider before whitelisting.'
  : 'Requires a hosting-provider-confirmed static outbound address. A website IP or observed IP is not a substitute.';

 const observe = async () => {
  setBusy('observe'); setError(''); setNotice('');
  try {
   const {data} = await api.post('/server/observe-egress');
   setDetails(current => ({...current, observation: data.observation}));
   setNotice(data.cached ? 'Showing the recent server observation (cached for up to 60 seconds). No static IP was assigned.' : 'Outbound address observed. This does not reserve an IP or verify broker access.');
  } catch (e) { setError(errorText(e)); }
  finally { setBusy(''); }
 };
 const refreshEvents = async () => {
  setBusy('events'); setError('');
  try { const {data} = await api.get('/server/events'); setEvents(data.events); }
  catch (e) { setError(errorText(e)); }
  finally { setBusy(''); }
 };
 const sendTest = async () => {
  if (!receiver) return;
  setBusy('test'); setError(''); setNotice('');
  try {
   await api.post(receiver.receive_path.replace(/^\/api/, ''), {
    type: 'application_self_test', test_id: crypto.randomUUID(), sent_at: new Date().toISOString(),
   });
   setNotice('Test postback accepted by the real receiver. This is a synthetic transport check, not a broker delivery or a trade.');
   const {data} = await api.get('/server/events'); setEvents(data.events);
  } catch (e) { setError(errorText(e)); }
  finally { setBusy(''); }
 };
 const rotate = async () => {
  setBusy('rotate'); setError(''); setNotice('');
  try {
   const {data} = await api.post('/server/postback/rotate');
   setReceiver(data); setConfirmRotation(false);
   setNotice('Postback URL replaced. The previous URL can no longer receive messages. Update every sender using it; existing receipts are kept.');
  } catch (e) { setError(errorText(e)); }
  finally { setBusy(''); }
 };

 return <section id="server-details" className="server-details" data-testid="server-details-panel" aria-labelledby="server-details-heading">
  <header className="server-details-heading">
   <div className="server-title-group"><span className="server-title-icon"><Globe2 size={23}/></span><div><span className="server-eyebrow">SHARED CONNECTION FOUNDATION</span><h2 id="server-details-heading">Application server details</h2></div></div>
   <Badge tone={error ? 'amber' : receiver ? 'green' : 'muted'} id="server-receiver-status">{error ? 'CHECK CONNECTION' : receiver ? 'JSON RECEIVER READY' : 'CONNECTING'}</Badge>
  </header>
  <p className="server-intro">One server address, with a private postback inbox for this workspace. Use it with services that support the JSON contract below. Each broker still needs its own credentials and compatible adapter.</p>
  {error && <div className="server-error" role="alert" data-testid="server-details-error"><span>{error}</span><Button type="button" variant="outline" disabled={!!busy} onClick={load} data-testid="server-details-retry">Retry details</Button></div>}
  <div className="server-details-grid">
   <div className="server-addresses">
    <DetailRow id="app-name" label="Application name" value={details?.app_name || 'EDGE INDIA Research'} copyValue={details?.app_name || 'EDGE INDIA Research'} note="Your application identity; not a broker account or API key."/>
    <DetailRow id="website" label="Server / website address" value={serverOrigin || 'Not configured — contact the app operator'} copyValue={serverOrigin} note={serverOrigin?.includes('.preview.') ? 'Current configured HTTPS preview address. A reachable preview is not a permanent or broker-approved hostname.' : 'Configured public application address. Confirm that your broker accepts this hostname.'}/>
    <DetailRow id="api-base" label="API base address" value={serverOrigin ? `${serverOrigin}/api` : 'Not configured — contact the app operator'} copyValue={serverOrigin ? `${serverOrigin}/api` : null} note="Application API base, not an OAuth redirect or a broker API address."/>
    <DetailRow id="postback" label="Postback URL" value={postbackUrl || unavailable} copyValue={postbackUrl} note="Private send-only address for this workspace. Keep it secret; anyone with the URL can submit unverified messages."/>
    <DetailRow id="redirect" label="OAuth redirect" value="Broker-specific — use provider setup below" note="The generic postback URL does not authorize accounts. There is no universal OAuth callback or credential."/>
   </div>
   <aside className="server-network" aria-label="Outbound network details">
    <h3>Outbound network</h3><p>These are server-side addresses, not your browser’s IP or the website’s DNS address.</p>
    <DetailRow id="primary-ip" label="Primary static IP" value={ipValue('primary_ip')} copyValue={details?.primary_ip} note={ipNote('primary_ip')}/>
    <DetailRow id="secondary-ip" label="Secondary static IP" value={ipValue('secondary_ip')} copyValue={details?.secondary_ip} note={ipNote('secondary_ip')}/>
    <DetailRow id="observed-ip" label="Observed outbound IP" value={observation?.ip || (details ? 'Not checked yet — use the button below' : unavailable)} copyValue={observation?.ip} note={observation ? `Observed ${formatTime(observation.observed_at)} IST. Current observation only; NOT reserved, static, or guaranteed for broker whitelisting.` : 'Checks the backend through ipify. This does not allocate a primary or secondary address.'}/>
    <Button type="button" variant="outline" data-testid="observe-server-ip" disabled={!!busy || !details} onClick={observe}>{busy === 'observe' ? <LoaderCircle size={15} className="spin"/> : <RefreshCw size={15}/>} {busy === 'observe' ? 'Checking server…' : 'Check outbound IP'}</Button>
   </aside>
  </div>
  <div className="server-contract" data-testid="server-receiver-contract"><span><b>POST</b> application/json</span><span>Object or array · 256 KiB maximum</span><span>202 new · 200 duplicate</span><span>Encrypted · 30-day retention</span></div>
  <div className="server-actions">
   <Button type="button" variant="outline" disabled={!!busy || !receiver} onClick={sendTest} data-testid="send-test-postback">{busy === 'test' ? <LoaderCircle size={15} className="spin"/> : <Send size={15}/>} Send test postback</Button>
   <Button type="button" variant="ghost" disabled={!!busy || !receiver || confirmRotation} onClick={() => setConfirmRotation(true)} data-testid="rotate-postback"><RotateCcw size={15}/> Replace postback URL</Button>
   <span>A test checks transport only, never broker authentication.</span>
  </div>
  {confirmRotation && <div className="server-rotation" role="alert" data-testid="postback-rotation-confirmation"><div><b>Replace this workspace’s postback URL?</b><p>The old URL will stop accepting messages immediately. Update all senders afterward. Existing receipts will remain.</p></div><div className="server-actions"><Button type="button" variant="outline" disabled={!!busy} onClick={() => setConfirmRotation(false)} data-testid="cancel-postback-rotation">Cancel</Button><Button type="button" className="primary-button" disabled={!!busy} onClick={rotate} data-testid="confirm-postback-rotation">{busy === 'rotate' ? 'Replacing…' : 'Confirm replacement'}</Button></div></div>}
  {notice && <p className="server-notice" role="status" data-testid="server-action-notice">{notice}</p>}
  <div className="server-inbox" data-testid="postback-inbox">
   <div className="server-inbox-heading"><div><Inbox size={18}/><h3>Postback receipts</h3><span>{events.length} recent</span></div><Button type="button" variant="ghost" disabled={!!busy || !receiver} onClick={refreshEvents} data-testid="refresh-postback-inbox"><RefreshCw size={15} className={busy === 'events' ? 'spin' : ''}/> Refresh inbox</Button></div>
   <p>Latest 12 receipts for this workspace. Metadata only; message contents and credentials are not displayed.</p>
   {events.length ? <ul className="server-receipts">{events.map(event => <li key={event.id} data-testid="postback-receipt"><div><b>{event.kind === 'SELF_LABELLED_TEST' ? 'Self-labelled test receipt' : 'Inbound JSON receipt'}</b><small>{formatTime(event.received_at)} IST · {event.payload_type} · {event.size_bytes} bytes</small></div><span className="server-unverified">UNVERIFIED</span></li>)}</ul> : <div className="server-inbox-empty" data-testid="postback-inbox-empty">{busy === 'load' ? 'Loading private inbox…' : error ? 'Inbox could not be refreshed. Retry the connection above.' : 'No receipts yet. Send a test postback to check your receiving address.'}</div>}
  </div>
  <footer className="server-boundary"><ShieldCheck size={18}/><span>Receiving a message does not prove its sender. No broker signatures are verified here, and receipts never change orders, paper trades, balances, or AI decisions. Services requiring signatures, challenges, different formats, or specific acknowledgements need a broker-specific adapter.</span></footer>
 </section>;
}
