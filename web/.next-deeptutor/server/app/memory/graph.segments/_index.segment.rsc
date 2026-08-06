1:"$Sreact.fragment"
3:I[812157,["/_next/static/chunks/0~s~bmtt5knv9.js","/_next/static/chunks/04d401-~5u4ud.js","/_next/static/chunks/0i.l9589uvx0j.js","/_next/static/chunks/03p-gkhmpfq_s.js"],"AppShellProvider"]
4:I[849887,["/_next/static/chunks/0~s~bmtt5knv9.js","/_next/static/chunks/04d401-~5u4ud.js","/_next/static/chunks/0i.l9589uvx0j.js","/_next/static/chunks/03p-gkhmpfq_s.js"],"I18nClientBridge"]
5:I[339756,["/_next/static/chunks/0~s~bmtt5knv9.js","/_next/static/chunks/04d401-~5u4ud.js","/_next/static/chunks/0i.l9589uvx0j.js","/_next/static/chunks/03p-gkhmpfq_s.js"],"default"]
6:I[837457,["/_next/static/chunks/0~s~bmtt5knv9.js","/_next/static/chunks/04d401-~5u4ud.js","/_next/static/chunks/0i.l9589uvx0j.js","/_next/static/chunks/03p-gkhmpfq_s.js"],"default"]
7:I[73278,["/_next/static/chunks/0~s~bmtt5knv9.js","/_next/static/chunks/04d401-~5u4ud.js","/_next/static/chunks/0i.l9589uvx0j.js","/_next/static/chunks/03p-gkhmpfq_s.js"],"default"]
:HL["/_next/static/chunks/145f069teoa7h.css","style"]
:HL["/_next/static/chunks/0cu0c5njb9oxq.css","style"]
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
  0:{"rsc":["$","$1","c",{"children":[[["$","link","0",{"rel":"stylesheet","href":"/_next/static/chunks/145f069teoa7h.css","precedence":"next"}],["$","link","1",{"rel":"stylesheet","href":"/_next/static/chunks/0cu0c5njb9oxq.css","precedence":"next"}],["$","script","script-0",{"src":"/_next/static/chunks/0~s~bmtt5knv9.js","async":true}],["$","script","script-1",{"src":"/_next/static/chunks/04d401-~5u4ud.js","async":true}],["$","script","script-2",{"src":"/_next/static/chunks/0i.l9589uvx0j.js","async":true}],["$","script","script-3",{"src":"/_next/static/chunks/03p-gkhmpfq_s.js","async":true}]],["$","html",null,{"lang":"en","suppressHydrationWarning":true,"data-scroll-behavior":"smooth","className":"geist_f8f0a9da-module__hptJ_W__variable lora_800b91ea-module__rFdvOq__variable","children":[["$","head",null,{"children":["$","script",null,{"dangerouslySetInnerHTML":{"__html":"$2"},"suppressHydrationWarning":true}]}],["$","body",null,{"className":"font-sans bg-[var(--background)] text-[var(--foreground)]","suppressHydrationWarning":true,"children":["$","$L3",null,{"children":[["$","$L4",null,{"children":["$","$L5",null,{"parallelRouterKey":"children","template":["$","$L6",null,{}],"notFound":[[["$","title",null,{"children":"404: This page could not be found."}],["$","div",null,{"style":{"fontFamily":"system-ui,\"Segoe UI\",Roboto,Helvetica,Arial,sans-serif,\"Apple Color Emoji\",\"Segoe UI Emoji\"","height":"100vh","textAlign":"center","display":"flex","flexDirection":"column","alignItems":"center","justifyContent":"center"},"children":["$","div",null,{"children":[["$","style",null,{"dangerouslySetInnerHTML":{"__html":"body{color:#000;background:#fff;margin:0}.next-error-h1{border-right:1px solid rgba(0,0,0,.3)}@media (prefers-color-scheme:dark){body{color:#fff;background:#000}.next-error-h1{border-right:1px solid rgba(255,255,255,.3)}}"}}],["$","h1",null,{"className":"next-error-h1","style":{"display":"inline-block","margin":"0 20px 0 0","padding":"0 23px 0 0","fontSize":24,"fontWeight":500,"verticalAlign":"top","lineHeight":"49px"},"children":404}],["$","div",null,{"style":{"display":"inline-block"},"children":["$","h2",null,{"style":{"fontSize":14,"fontWeight":400,"lineHeight":"49px","margin":0},"children":"This page could not be found."}]}]]}]}]],[]]}]}],["$","$L7",null,{}]]}]}]]}]]}],"isPartial":false,"staleTime":300,"varyParams":null,"buildId":"mIpATQgctdZDqy-G9VrDP"}
