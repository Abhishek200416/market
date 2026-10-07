import {Link} from 'react-router-dom';
import {ArrowUpRight,ArrowRight,Wallet,TrendingUp,ShieldCheck,Activity,Radio,Sparkles,SlidersHorizontal,ChevronRight,LockKeyhole,Network,Check} from 'lucide-react';
import {PageHeading,Badge,Metric,PanelHeading} from '../components/TerminalUI';
import {MarketChart} from '../components/MarketChart';
import {Button} from '../components/ui/button';
import {money} from '../lib/api';
import {WorkspaceGuide} from '../components/WorkspaceGuide';

const watchlist=[['NIFTY 50','NSE · Index','N','NSE:NIFTY50-INDEX'],['BANK NIFTY','NSE · Index','B','NSE:NIFTYBANK-INDEX'],['RELIANCE','NSE · Energy','R','NSE:RELIANCE-EQ'],['HDFC BANK','NSE · Banking','H','NSE:HDFCBANK-EQ'],['INFOSYS','NSE · IT','I','NSE:INFY-EQ']];

const Watchlist=({overview,connected})=><section className="watchlist-panel">
 <PanelHeading title="Watchlist" id="watchlist"><Link to="/markets" data-testid="view-markets-link" className="icon-button" title="View all markets"><ArrowUpRight size={17}/></Link></PanelHeading>
 <div className="watchlist-labels"><span>INSTRUMENT</span><span>LAST / STATUS</span></div>
 {watchlist.map(([name,desc,initial,symbol],i)=>{
  const quote=overview?.quotes?.find(q=>q.symbol===symbol);
  return <Link to={`/markets?instrument=${encodeURIComponent(symbol)}`} className="watchlist-row" data-testid={`watchlist-row-${i}`} key={name}>
   <span className={`stock-monogram mono-${i}`}>{initial}</span><div><b>{name}</b><small>{desc}</small></div>
   <div className="watchlist-value"><b>{quote?.ltp?.toLocaleString('en-IN')||'—'}</b><small>{quote?.freshness||(connected?'Awaiting quote':'Not connected')}</small></div>
  </Link>;
 })}
 <Link to="/markets" data-testid="watchlist-view-all" className="view-all-link">View all instruments <ArrowRight size={13}/></Link>
 <div className="data-integrity-note"><ShieldCheck size={13}/><span>Verified data. Never fabricated.</span></div>
</section>;

const SystemPulse=({overview})=>{
 const feed=overview?.connections?.find(c=>c.provider===(overview?.market_provider||'upstox'))?.status;
 const ai=overview?.connections?.find(c=>c.provider==='gemini')?.status;
 const rows=[['Market feed',feed==='CONNECTED'?'Connected':feed==='ERROR'?'Error':'Not connected',feed==='CONNECTED'?'green':'amber'],['AI engine',ai==='CONNECTED'?'Connected':ai==='ERROR'?'Error':'Not connected',ai==='CONNECTED'?'green':'amber'],['Database',overview?.database==='CONNECTED'?'Connected':'Checking…',overview?.database==='CONNECTED'?'green':'amber'],['Execution','Paper only','cyan']];
 return <section className="system-preview-panel">
  <PanelHeading title="System pulse" icon={Activity} id="system-pulse"><Link to="/health" className="icon-button" data-testid="view-system-health" title="View health"><ArrowUpRight size={16}/></Link></PanelHeading>
  {rows.map(([label,value,tone])=><div className="system-pulse-row" key={label} data-testid={`system-pulse-${label.replaceAll(' ','-').toLowerCase()}`}><span>{label}</span><span><i className={`status-dot ${tone}`}/>{value}</span></div>)}
  <div className="pulse-footer"><span className="small-label">LIVE ELIGIBILITY</span><Link to="/eligibility" data-testid="eligibility-link">NO-GO <ChevronRight size={14}/></Link></div>
 </section>;
};

export default function Dashboard({overview,user}){
 const account=overview?.account;
 const providerId=overview?.market_provider||'upstox';
 const provider=providerId==='upstox'?'Upstox':'FYERS';
 const connected=overview?.connections?.find(x=>x.provider===providerId)?.status==='CONNECTED';
 const aiConnected=overview?.connections?.find(x=>x.provider==='gemini')?.status==='CONNECTED';
 return <>
  <PageHeading title="Market overview" subtitle="A clear view of the market. A disciplined approach to every trade.">
   <Badge tone="muted" id="market-session-status">{connected?`${provider.toUpperCase()} CONNECTED`:'AWAITING MARKET DATA'}</Badge>
   <Button variant="outline" asChild data-testid="dashboard-connections-button"><Link to="/connections"><SlidersHorizontal size={15}/> Configure workspace</Link></Button>
  </PageHeading>
  <WorkspaceGuide overview={overview}/>
  <div className="connection-banner" data-testid="connection-banner">
   <div className="banner-icon"><Radio size={19}/></div>
   <div><b>{connected&&aiConnected?'Your connections are ready. Let the evidence lead.':'Your terminal is ready. Let’s connect the market.'}</b>
    <p>{connected&&aiConnected?'Research requires fresh source data. Execution remains paper-only and independently risk-checked.':`Connect ${provider} for market data and Gemini for intelligence. Until then, all signals remain on hold.`}</p>
   </div><Link to="/connections" data-testid="setup-connections-link">{connected?'Manage connections':'Set up connections'} <ArrowRight size={16}/></Link>
  </div>
  <div className="metrics-row">
   <Metric label={account?'Paper account equity':'Starting paper capital'} value={money(account?account.equity:1000000)} note={account?'INR · Paper account':'INR · Opening your workspace'} icon={Wallet} id="equity-metric"/>
   <Metric label="Realized P&L" value={account?money(account.realized_pnl):'—'} note={account?`${account.trades.length} closed trades`:'No account connected'} icon={TrendingUp} id="pnl-metric"/>
   <Metric label="Portfolio drawdown" value={account?.drawdown!=null?`${account.drawdown.toFixed(2)}%`:'—'} note={`Daily loss limit ${Number(account?.risk?.daily_loss_limit??2).toFixed(2)}%`} icon={ShieldCheck} id="drawdown-metric"/>
   <Metric label="Market regime" value="UNDETERMINED" note="Requires validated regime analysis" icon={Activity} id="regime-metric"/>
  </div>
  <div className="dashboard-main-grid"><MarketChart user={user} connected={connected} provider={provider}/><Watchlist overview={overview} connected={connected}/></div>
  <div className="dashboard-bottom-grid">
   <section className="intelligence-panel">
    <PanelHeading title="AI intelligence" icon={Sparkles} id="ai-intelligence"><Badge id="ai-state-badge">{aiConnected?'AVAILABLE':'STANDBY'}</Badge></PanelHeading>
    <div className="ai-decision"><div><span className="small-label">CURRENT POSTURE</span><h3 data-testid="decision-no-trade">NO TRADE</h3><p>Patience is a position.</p></div><span className="decision-icon"><ShieldCheck size={29} strokeWidth={1.2}/></span></div>
    <div className="agent-pipeline" data-testid="agent-pipeline">{['ANALYZE','DEBATE','RISK CHECK'].map((v,i)=><div key={v}><span className="agent-node">{i===0?<Activity size={15}/>:i===1?<Network size={15}/>:<ShieldCheck size={15}/>}</span><span>{v}</span>{i<2&&<span className="pipeline-line"/>}</div>)}</div>
    <div className="intelligence-footer"><span><i className="status-dot muted-dot"/>{aiConnected&&connected?'No independently validated trade setup':'Awaiting Gemini & market data'}</span><Link data-testid="ai-details-link" to="/signals"><ArrowUpRight size={15}/></Link></div>
   </section>
   <section className="risk-preview-panel">
    <PanelHeading title="Risk guardrails" icon={ShieldCheck} id="risk-guardrails"><Link className="text-link" to="/risk" data-testid="manage-risk-link">Manage <ArrowUpRight size={12}/></Link></PanelHeading>
    <div className="risk-preview-row"><span>Risk per trade</span><b data-testid="risk-preview-per-trade">{account?.risk.risk_per_trade??0.5}%</b></div>
    <div className="risk-preview-row"><span>Daily loss limit</span><b data-testid="risk-preview-daily-loss">{Number(account?.risk.daily_loss_limit??2).toFixed(2)}%</b></div>
    <div className="risk-preview-row"><span>Loss streak cooldown</span><b>{account?.risk.max_consecutive_losses??3} losses</b></div>
    <div className="risk-preview-row"><span>Real broker execution</span><span className="disabled-label"><LockKeyhole size={11}/> DISABLED</span></div>
    <div className="risk-enforced-note"><Check size={13}/> Deterministic. Never overridden by AI.</div>
   </section><SystemPulse overview={overview}/>
  </div>
  <div className="dashboard-end-note" data-testid="research-principle"><ShieldCheck size={14}/><span>Good research questions every signal. Good risk management knows when to wait.</span><span>DATA INTEGRITY FIRST</span></div>
 </>;
}