import type { Metadata } from "next";
import { Hanken_Grotesk, IBM_Plex_Mono, Source_Serif_4 } from "next/font/google";
import "./globals.css";

/* next/font downloads these at build time and serves them from this origin. That matters more
   than usual here: the dashboard is tailnet-only, so a <link> to fonts.googleapis.com made the
   page's typography depend on the client having public internet, and fell back to Georgia when
   it did not.
   Source Serif 4 replaces Newsreader as the reading face -- same warmth, noticeably larger
   x-height, which is what makes the difference at these sizes. */
const sans = Hanken_Grotesk({ subsets: ["latin"], variable: "--font-hanken", display: "swap" });
const serif = Source_Serif_4({
  subsets: ["latin"],
  style: ["normal", "italic"],
  variable: "--font-source-serif",
  display: "swap",
});
const mono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-plex-mono",
  display: "swap",
});

const FAVICON =
  "data:image/svg+xml," +
  encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect width="24" height="24" rx="6" fill="#1a1915"/><path d="M4 17l4.5-5 3.5 3L20 7" stroke="#C15F3C" stroke-width="2.2" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>`
  );

export const metadata: Metadata = {
  title: "Macro Brief",
  description: "07:00 JST pre-open causal analysis for Japanese equities",
  icons: { icon: FAVICON },
};

/* Runs before first paint so a dark-mode reader never gets a full-screen cream flash at 06:40.
   Reading it in React state instead would paint the default first, and on this page the default
   is the brightest thing the app can show. */
const THEME_INIT = `try{var d=document.documentElement,s=localStorage;
d.dataset.theme=s.getItem("df-theme")==="dark"?"dark":"paper";
var z=s.getItem("df-size");d.dataset.size=(z==="s"||z==="l")?z:"m";}catch(e){}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      data-theme="paper"
      data-size="m"
      className={`${sans.variable} ${serif.variable} ${mono.variable}`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
