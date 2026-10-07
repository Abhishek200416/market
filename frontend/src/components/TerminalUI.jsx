import { Link } from 'react-router-dom';
import { ArrowUpRight, Cable, Radar } from 'lucide-react';
import { Button } from './ui/button';

export const Badge = ({children, tone='muted', id}) => <span data-testid={id} className={`status-badge ${tone}`}><i/>{children}</span>;
export const PageHeading = ({eyebrow='RESEARCH WORKSPACE', title, subtitle, children}) => <div className="page-heading"><div><div className="eyebrow" data-testid="page-eyebrow">{eyebrow}</div><h1 data-testid="page-title">{title}</h1>{subtitle&&<p data-testid="page-subtitle">{subtitle}</p>}</div><div className="heading-actions">{children}</div></div>;
export const PanelHeading = ({title, icon:Icon, children, id}) => <div className="panel-heading"><h2 data-testid={`${id}-title`}>{Icon&&<Icon size={16}/>} {title}</h2>{children}</div>;
export const EmptyState = ({title, text, icon:Icon=Radar, action, id='empty-state'}) => <div className="empty-state" data-testid={id}><div className="empty-icon"><Icon size={25} strokeWidth={1.4}/></div><h3>{title}</h3><p>{text}</p>{action}</div>;
export const ConnectButton = ({id='connect-provider', small=false, provider='Upstox'}) => <Button asChild size={small?'sm':'default'} className="primary-button" data-testid={id}><Link to="/connections"><Cable size={14}/> Connect {provider} <ArrowUpRight size={14}/></Link></Button>;
export const Metric = ({label,value,note,icon:Icon,tone='',id}) => <div className="metric" data-testid={id}><div className="metric-label">{label}{Icon&&<Icon size={15}/>}</div><div className={`metric-value ${tone}`}>{value}</div><div className="metric-note">{note}</div></div>;