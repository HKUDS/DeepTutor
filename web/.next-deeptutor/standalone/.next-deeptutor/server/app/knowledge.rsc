1:"$Sreact.fragment"
3:I[812157,["/_next/static/chunks/0~s~bmtt5knv9.js","/_next/static/chunks/04d401-~5u4ud.js","/_next/static/chunks/0i.l9589uvx0j.js","/_next/static/chunks/03p-gkhmpfq_s.js"],"AppShellProvider"]
4:I[849887,["/_next/static/chunks/0~s~bmtt5knv9.js","/_next/static/chunks/04d401-~5u4ud.js","/_next/static/chunks/0i.l9589uvx0j.js","/_next/static/chunks/03p-gkhmpfq_s.js"],"I18nClientBridge"]
5:I[339756,["/_next/static/chunks/0~s~bmtt5knv9.js","/_next/static/chunks/04d401-~5u4ud.js","/_next/static/chunks/0i.l9589uvx0j.js","/_next/static/chunks/03p-gkhmpfq_s.js"],"default"]
6:I[837457,["/_next/static/chunks/0~s~bmtt5knv9.js","/_next/static/chunks/04d401-~5u4ud.js","/_next/static/chunks/0i.l9589uvx0j.js","/_next/static/chunks/03p-gkhmpfq_s.js"],"default"]
7:I[73278,["/_next/static/chunks/0~s~bmtt5knv9.js","/_next/static/chunks/04d401-~5u4ud.js","/_next/static/chunks/0i.l9589uvx0j.js","/_next/static/chunks/03p-gkhmpfq_s.js"],"default"]
8:I[868758,["/_next/static/chunks/0~s~bmtt5knv9.js","/_next/static/chunks/04d401-~5u4ud.js","/_next/static/chunks/0i.l9589uvx0j.js","/_next/static/chunks/03p-gkhmpfq_s.js","/_next/static/chunks/0qzjvz1_hg3zp.js","/_next/static/chunks/024xzih1.~zoj.js"],"CapabilityAccessProvider"]
9:I[199765,["/_next/static/chunks/0~s~bmtt5knv9.js","/_next/static/chunks/04d401-~5u4ud.js","/_next/static/chunks/0i.l9589uvx0j.js","/_next/static/chunks/03p-gkhmpfq_s.js","/_next/static/chunks/0qzjvz1_hg3zp.js","/_next/static/chunks/024xzih1.~zoj.js"],"default"]
10:I[168027,["/_next/static/chunks/0~s~bmtt5knv9.js","/_next/static/chunks/04d401-~5u4ud.js","/_next/static/chunks/0i.l9589uvx0j.js","/_next/static/chunks/03p-gkhmpfq_s.js"],"default",1]
:HL["/_next/static/chunks/145f069teoa7h.css","style"]
:HL["/_next/static/chunks/0cu0c5njb9oxq.css","style"]
:HL["/_next/static/media/8c2eb9ceedecfc8e-s.p.0oeo8epbafgia.woff2","font",{"crossOrigin":"","type":"font/woff2"}]
:HL["/_next/static/media/caa3a2e1cccd8315-s.p.09~u27dqhyhd6.woff2","font",{"crossOrigin":"","type":"font/woff2"}]
2:T479,
    (function() {
      try {
        const stored = localStorage.getItem('deeptutor-theme');

        document.documentElement.classList.remove('dark', 'theme-glass', 'theme-snow');

        if (stored === 'dark') {
          document.documentElement.classList.add('dark');
        } else if (stored === 'glass') {
          document.documentElement.classList.add('dark', 'theme-glass');
        } else if (stored === 'snow') {
          document.documentElement.classList.add('theme-snow');
        } else if (stored === 'light') {
          // already clean
        } else {
          // No stored preference: Default (snow) for light systems,
          // Dark for prefers-color-scheme: dark.
          if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
            document.documentElement.classList.add('dark');
            localStorage.setItem('deeptutor-theme', 'dark');
          } else {
            document.documentElement.classList.add('theme-snow');
            localStorage.setItem('deeptutor-theme', 'snow');
          }
        }
      } catch (e) {
        /* localStorage may be disabled */
      }
    })();
  0:{"P":null,"c":["","knowledge"],"q":"","i":false,"f":[[["",{"children":["(utility)",{"children":["knowledge",{"children":["__PAGE__",{}]}]}]},"$undefined","$undefined",16],[["$","$1","c",{"children":[[["$","link","0",{"rel":"stylesheet","href":"/_next/static/chunks/145f069teoa7h.css","precedence":"next","crossOrigin":"$undefined","nonce":"$undefined"}],["$","link","1",{"rel":"stylesheet","href":"/_next/static/chunks/0cu0c5njb9oxq.css","precedence":"next","crossOrigin":"$undefined","nonce":"$undefined"}],["$","script","script-0",{"src":"/_next/static/chunks/0~s~bmtt5knv9.js","async":true,"nonce":"$undefined"}],["$","script","script-1",{"src":"/_next/static/chunks/04d401-~5u4ud.js","async":true,"nonce":"$undefined"}],["$","script","script-2",{"src":"/_next/static/chunks/0i.l9589uvx0j.js","async":true,"nonce":"$undefined"}],["$","script","script-3",{"src":"/_next/static/chunks/03p-gkhmpfq_s.js","async":true,"nonce":"$undefined"}]],["$","html",null,{"lang":"en","suppressHydrationWarning":true,"data-scroll-behavior":"smooth","className":"geist_f8f0a9da-module__hptJ_W__variable lora_800b91ea-module__rFdvOq__variable","children":[["$","head",null,{"children":["$","script",null,{"dangerouslySetInnerHTML":{"__html":"$2"},"suppressHydrationWarning":true}]}],["$","body",null,{"className":"font-sans bg-[var(--background)] text-[var(--foreground)]","suppressHydrationWarning":true,"children":["$","$L3",null,{"children":[["$","$L4",null,{"children":["$","$L5",null,{"parallelRouterKey":"children","error":"$undefined","errorStyles":"$undefined","errorScripts":"$undefined","template":["$","$L6",null,{}],"templateStyles":"$undefined","templateScripts":"$undefined","notFound":[[["$","title",null,{"children":"404: This page could not be found."}],["$","div",null,{"style":{"fontFamily":"system-ui,\"Segoe UI\",Roboto,Helvetica,Arial,sans-serif,\"Apple Color Emoji\",\"Segoe UI Emoji\"","height":"100vh","textAlign":"center","display":"flex","flexDirection":"column","alignItems":"center","justifyContent":"center"},"children":["$","div",null,{"children":[["$","style",null,{"dangerouslySetInnerHTML":{"__html":"body{color:#000;background:#fff;margin:0}.next-error-h1{border-right:1px solid rgba(0,0,0,.3)}@media (prefers-color-scheme:dark){body{color:#fff;background:#000}.next-error-h1{border-right:1px solid rgba(255,255,255,.3)}}"}}],["$","h1",null,{"className":"next-error-h1","style":{"display":"inline-block","margin":"0 20px 0 0","padding":"0 23px 0 0","fontSize":24,"fontWeight":500,"verticalAlign":"top","lineHeight":"49px"},"children":404}],["$","div",null,{"style":{"display":"inline-block"},"children":["$","h2",null,{"style":{"fontSize":14,"fontWeight":400,"lineHeight":"49px","margin":0},"children":"This page could not be found."}]}]]}]}]],[]],"forbidden":"$undefined","unauthorized":"$undefined"}]}],["$","$L7",null,{}]]}]}]]}]]}],{"children":[["$","$1","c",{"children":[[["$","script","script-0",{"src":"/_next/static/chunks/0qzjvz1_hg3zp.js","async":true,"nonce":"$undefined"}],["$","script","script-1",{"src":"/_next/static/chunks/024xzih1.~zoj.js","async":true,"nonce":"$undefined"}]],["$","$L8",null,{"children":["$","$L9",null,{"sidebar":"$La","children":"$Lb"}]}]]}],{"children":["$Lc",{"children":["$Ld",{},null,false,null]},null,false,"$@e"]},null,false,null]},null,false,null],"$Lf",false]],"m":"$undefined","G":["$10",["$L11","$L12"]],"S":true,"h":null,"s":"$undefined","l":"$undefined","p":"$undefined","d":"$undefined","b":"mIpATQgctdZDqy-G9VrDP"}
13:I[409626,["/_next/static/chunks/0~s~bmtt5knv9.js","/_next/static/chunks/04d401-~5u4ud.js","/_next/static/chunks/0i.l9589uvx0j.js","/_next/static/chunks/03p-gkhmpfq_s.js","/_next/static/chunks/0qzjvz1_hg3zp.js","/_next/static/chunks/024xzih1.~zoj.js"],"default"]
14:I[145244,["/_next/static/chunks/0~s~bmtt5knv9.js","/_next/static/chunks/04d401-~5u4ud.js","/_next/static/chunks/0i.l9589uvx0j.js","/_next/static/chunks/03p-gkhmpfq_s.js","/_next/static/chunks/0qzjvz1_hg3zp.js","/_next/static/chunks/024xzih1.~zoj.js"],"default"]
15:I[347257,["/_next/static/chunks/0~s~bmtt5knv9.js","/_next/static/chunks/04d401-~5u4ud.js","/_next/static/chunks/0i.l9589uvx0j.js","/_next/static/chunks/03p-gkhmpfq_s.js"],"ClientPageRoot"]
16:I[841328,["/_next/static/chunks/0~s~bmtt5knv9.js","/_next/static/chunks/04d401-~5u4ud.js","/_next/static/chunks/0i.l9589uvx0j.js","/_next/static/chunks/03p-gkhmpfq_s.js","/_next/static/chunks/0qzjvz1_hg3zp.js","/_next/static/chunks/024xzih1.~zoj.js","/_next/static/chunks/0fidnuylvjfwd.js","/_next/static/chunks/0aidtfdwr~u2s.js"],"default"]
19:I[897367,["/_next/static/chunks/0~s~bmtt5knv9.js","/_next/static/chunks/04d401-~5u4ud.js","/_next/static/chunks/0i.l9589uvx0j.js","/_next/static/chunks/03p-gkhmpfq_s.js"],"OutletBoundary"]
1a:"$Sreact.suspense"
1d:I[897367,["/_next/static/chunks/0~s~bmtt5knv9.js","/_next/static/chunks/04d401-~5u4ud.js","/_next/static/chunks/0i.l9589uvx0j.js","/_next/static/chunks/03p-gkhmpfq_s.js"],"ViewportBoundary"]
1f:I[897367,["/_next/static/chunks/0~s~bmtt5knv9.js","/_next/static/chunks/04d401-~5u4ud.js","/_next/static/chunks/0i.l9589uvx0j.js","/_next/static/chunks/03p-gkhmpfq_s.js"],"MetadataBoundary"]
a:["$","$L13",null,{}]
b:["$","$L14",null,{"children":["$","$L5",null,{"parallelRouterKey":"children","error":"$undefined","errorStyles":"$undefined","errorScripts":"$undefined","template":["$","$L6",null,{}],"templateStyles":"$undefined","templateScripts":"$undefined","notFound":[[["$","title",null,{"children":"404: This page could not be found."}],["$","div",null,{"style":"$0:f:0:1:0:props:children:1:props:children:1:props:children:props:children:0:props:children:props:notFound:0:1:props:style","children":["$","div",null,{"children":[["$","style",null,{"dangerouslySetInnerHTML":{"__html":"body{color:#000;background:#fff;margin:0}.next-error-h1{border-right:1px solid rgba(0,0,0,.3)}@media (prefers-color-scheme:dark){body{color:#fff;background:#000}.next-error-h1{border-right:1px solid rgba(255,255,255,.3)}}"}}],["$","h1",null,{"className":"next-error-h1","style":"$0:f:0:1:0:props:children:1:props:children:1:props:children:props:children:0:props:children:props:notFound:0:1:props:children:props:children:1:props:style","children":404}],["$","div",null,{"style":"$0:f:0:1:0:props:children:1:props:children:1:props:children:props:children:0:props:children:props:notFound:0:1:props:children:props:children:2:props:style","children":["$","h2",null,{"style":"$0:f:0:1:0:props:children:1:props:children:1:props:children:props:children:0:props:children:props:notFound:0:1:props:children:props:children:2:props:children:props:style","children":"This page could not be found."}]}]]}]}]],[]],"forbidden":"$undefined","unauthorized":"$undefined"}]}]
c:["$","$1","c",{"children":[null,["$","$L5",null,{"parallelRouterKey":"children","error":"$undefined","errorStyles":"$undefined","errorScripts":"$undefined","template":["$","$L6",null,{}],"templateStyles":"$undefined","templateScripts":"$undefined","notFound":"$undefined","forbidden":"$undefined","unauthorized":"$undefined"}]]}]
d:["$","$1","c",{"children":[["$","$L15",null,{"Component":"$16","serverProvidedParams":{"searchParams":{},"params":{},"promises":["$@17","$@18"]}}],[["$","script","script-0",{"src":"/_next/static/chunks/0fidnuylvjfwd.js","async":true,"nonce":"$undefined"}],["$","script","script-1",{"src":"/_next/static/chunks/0aidtfdwr~u2s.js","async":true,"nonce":"$undefined"}]],["$","$L19",null,{"children":["$","$1a",null,{"name":"Next.MetadataOutlet","children":"$@1b"}]}]]}]
1c:[]
e:"$W1c"
f:["$","$1","h",{"children":[null,["$","$L1d",null,{"children":"$L1e"}],["$","div",null,{"hidden":true,"children":["$","$L1f",null,{"children":["$","$1a",null,{"name":"Next.Metadata","children":"$L20"}]}]}],["$","meta",null,{"name":"next-size-adjust","content":""}]]}]
11:["$","link","0",{"rel":"stylesheet","href":"/_next/static/chunks/145f069teoa7h.css","precedence":"next","crossOrigin":"$undefined","nonce":"$undefined"}]
12:["$","link","1",{"rel":"stylesheet","href":"/_next/static/chunks/0cu0c5njb9oxq.css","precedence":"next","crossOrigin":"$undefined","nonce":"$undefined"}]
17:{}
18:"$d:props:children:0:props:serverProvidedParams:params"
1e:[["$","meta","0",{"charSet":"utf-8"}],["$","meta","1",{"name":"viewport","content":"width=device-width, initial-scale=1"}]]
21:I[27201,["/_next/static/chunks/0~s~bmtt5knv9.js","/_next/static/chunks/04d401-~5u4ud.js","/_next/static/chunks/0i.l9589uvx0j.js","/_next/static/chunks/03p-gkhmpfq_s.js"],"IconMark"]
1b:null
20:[["$","title","0",{"children":"DeepTutor"}],["$","meta","1",{"name":"description","content":"Agent-native intelligent learning companion"}],["$","link","2",{"rel":"icon","href":"/favicon-16x16.png","sizes":"16x16","type":"image/png"}],["$","link","3",{"rel":"icon","href":"/favicon-32x32.png","sizes":"32x32","type":"image/png"}],["$","link","4",{"rel":"apple-touch-icon","href":"/apple-touch-icon.png"}],["$","$L21","5",{}]]
