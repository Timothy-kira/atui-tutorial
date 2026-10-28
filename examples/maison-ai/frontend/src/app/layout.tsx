import type { Metadata,Viewport } from 'next';
import '@copilotkit/react-core/v2/styles.css';
import './globals.css';
import './a2ui/workflows.css';
import './a2ui/streaming.css';
export const metadata: Metadata={title:'Maison AI — Your Personal Dining Assistant',description:'A DevFest hands-on demo with ADK, AG-UI and A2UI.'};
export const viewport:Viewport={width:'device-width',initialScale:1,viewportFit:'cover',interactiveWidget:'resizes-content'};
export default function Layout({children}:{children:React.ReactNode}){return <html lang="en" suppressHydrationWarning><head><link rel="preconnect" href="https://fonts.googleapis.com"/><link href="https://fonts.googleapis.com/css2?family=Google+Sans+Flex:opsz,wght@8..144,100..1000&display=swap" rel="stylesheet"/></head><body>{children}</body></html>;}
