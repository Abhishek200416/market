import {useTheme} from 'next-themes';
import {Moon,Sun,Monitor} from 'lucide-react';

export const ThemeToggle=()=>{
 const {resolvedTheme,setTheme}=useTheme();
 const light=resolvedTheme==='light';
 return <button type="button" className="theme-toggle" data-testid="theme-toggle" aria-label={`Switch to ${light?'dark':'light'} mode`} title={`Switch to ${light?'dark':'light'} mode`} onClick={()=>setTheme(light?'dark':'light')}>{light?<Moon size={18}/>:<Sun size={18}/>}<span>{light?'Dark':'Light'}</span></button>;
};
export const ThemePreferences=()=>{
 const {theme,setTheme}=useTheme();
 return <section className="theme-preferences" data-testid="appearance-settings"><div><h2>Appearance</h2><p>Choose a comfortable view. Your preference stays on this browser.</p></div><div className="theme-options" role="group" aria-label="Color theme">{[['light','Light',Sun],['dark','Dark',Moon],['system','System',Monitor]].map(([value,label,Icon])=><button type="button" key={value} data-testid={`theme-${value}`} className={theme===value?'selected':''} aria-pressed={theme===value} onClick={()=>setTheme(value)}><Icon size={17}/>{label}</button>)}</div></section>;
};
