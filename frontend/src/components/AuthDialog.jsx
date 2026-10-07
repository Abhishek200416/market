import {useState} from 'react';
import {ShieldCheck,ArrowRight,LoaderCircle} from 'lucide-react';
import {Dialog,DialogContent,DialogHeader,DialogTitle,DialogDescription} from './ui/dialog';
import {Button} from './ui/button';
import {api,errorText} from '../lib/api';

export const AuthDialog = ({open,onOpenChange,onSuccess}) => {
 const [mode,setMode]=useState('login'),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const [form,setForm]=useState({name:'',email:'',password:''});
 const submit=async e=>{e.preventDefault();setBusy(true);setError('');try{const {data}=await api.post(`/auth/${mode}`,{...form,name:form.name||'Researcher'});sessionStorage.setItem('terminal-csrf',data.csrf_token);onSuccess(data.user);onOpenChange(false);}catch(e){setError(errorText(e));}finally{setBusy(false);}};
 return <Dialog open={open} onOpenChange={onOpenChange}><DialogContent className="auth-dialog" data-testid="auth-dialog"><DialogHeader><div className="auth-symbol"><ShieldCheck size={24}/></div><DialogTitle data-testid="auth-title">{mode==='login'?'Welcome to your workspace.':'Your research starts here.'}</DialogTitle><DialogDescription data-testid="auth-description">{mode==='login'?'Sign in to continue your research.':'Create your private paper-trading account.'}</DialogDescription></DialogHeader><form onSubmit={submit} className="form-stack">
 {mode==='register'&&<label>Name<input data-testid="auth-name" required maxLength={60} value={form.name} onChange={e=>setForm({...form,name:e.target.value})} placeholder="Your name" autoComplete="name"/></label>}
 <label>Email address<input data-testid="auth-email" type="email" required value={form.email} onChange={e=>setForm({...form,email:e.target.value})} placeholder="you@example.com" autoComplete="email"/></label>
 <label>Password<input data-testid="auth-password" type="password" minLength={10} maxLength={72} required value={form.password} onChange={e=>setForm({...form,password:e.target.value})} placeholder="At least 10 characters" autoComplete={mode==='login'?'current-password':'new-password'}/></label>
 {error&&<div className="form-error" role="alert" data-testid="auth-error">{error}</div>}
 <Button data-testid="auth-submit" disabled={busy} className="primary-button">{busy?<LoaderCircle className="spin"/>:null}{mode==='login'?'Sign in':'Create account'}<ArrowRight size={15}/></Button>
 </form><button data-testid="auth-toggle" className="text-link auth-toggle" onClick={()=>{setMode(mode==='login'?'register':'login');setError('');}}>{mode==='login'?'New here? Create an account':'Already have an account? Sign in'}</button><div className="auth-footnote" data-testid="auth-paper-note"><ShieldCheck size={13}/> Paper trading only. No real orders.</div></DialogContent></Dialog>
};