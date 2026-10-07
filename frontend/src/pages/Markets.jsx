import {useState,useEffect} from 'react';
import {useSearchParams} from 'react-router-dom';
import {ArrowUpRight} from 'lucide-react';
import {PageHeading,Badge} from '../components/TerminalUI';
import {MarketChart} from '../components/MarketChart';
import {api,errorText} from '../lib/api';
import {toast} from '../components/ui/sonner';

export default function Markets({user,overview}){
 const [params,setParams]=useSearchParams(),[items,setItems]=useState([]),[search,setSearch]=useState('');
 const symbol=params.get('instrument')||'NSE:NIFTY50-INDEX';
 const providerId=overview?.market_provider||'upstox';
 const provider=providerId==='upstox'?'Upstox':'FYERS';
 useEffect(()=>{api.get('/markets/instruments').then(r=>setItems(r.data.instruments)).catch(e=>toast.error(errorText(e)));},[]);
 const current=items.find(i=>i.symbol===symbol)||items[0];
 const filtered=items.filter(i=>`${i.name} ${i.symbol}`.toLowerCase().includes(search.toLowerCase()));
 return <>
  <PageHeading eyebrow="MARKETS / INDIA" title="Market watch" subtitle="NSE indices and a focused universe of liquid Indian equities."><Badge id="markets-provider-badge" tone="cyan">{provider.toUpperCase()} · READ ONLY</Badge></PageHeading>
  <div className="filter-bar"><input data-testid="instrument-search" aria-label="Search instruments" value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search instruments…"/><Badge id="instrument-count">{items.length} INSTRUMENTS</Badge></div>
  <div className="markets-grid">
   <MarketChart user={user} symbol={current?.symbol} name={current?.name} provider={provider} connected={overview?.connections?.find(c=>c.provider===providerId)?.status==='CONNECTED'} large/>
   <div className="instrument-list">{filtered.map(item=><button data-testid={`instrument-${item.symbol.replaceAll(':','-')}`} key={item.symbol} className={current?.symbol===item.symbol?'selected':''} onClick={()=>setParams({instrument:item.symbol})}><span>{item.name}<small>{item.type} · {item.sector}</small></span><ArrowUpRight size={16}/></button>)}{items.length>0&&!filtered.length&&<p className="muted" data-testid="instrument-search-empty">No matching instruments.</p>}</div>
  </div>
  <div className="security-note" data-testid="market-data-policy">Completed candles only. Source timestamps remain visible. REST refresh every 15 seconds; WebSocket streaming is not enabled in this release.</div>
 </>;
}