import { useMemo } from 'react'
import Markdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import type { PluggableList } from 'unified'
import 'katex/dist/katex.min.css'
import { markdownUrlTransform, prepareAssistantMarkdown } from './markdown'

const remarkPlugins: PluggableList = [remarkGfm, remarkMath]
const rehypePlugins: PluggableList = [
  [rehypeKatex, { throwOnError: false, strict: 'ignore' }],
]

function codeLanguage(className?: string): string {
  return /language-([A-Za-z0-9_+#.-]+)/.exec(className || '')?.[1] || ''
}

const components: Components = {
  p: ({ node: _node, ...props }) => <p className="markdown-p" {...props} />,
  h1: ({ node: _node, ...props }) => <h1 className="markdown-h1" {...props} />,
  h2: ({ node: _node, ...props }) => <h2 className="markdown-h2" {...props} />,
  h3: ({ node: _node, ...props }) => <h3 className="markdown-h3" {...props} />,
  h4: ({ node: _node, ...props }) => <h4 className="markdown-h4" {...props} />,
  h5: ({ node: _node, ...props }) => <h5 className="markdown-h5" {...props} />,
  h6: ({ node: _node, ...props }) => <h6 className="markdown-h6" {...props} />,
  ul: ({ node: _node, ...props }) => <ul className="markdown-ul" {...props} />,
  ol: ({ node: _node, ...props }) => <ol className="markdown-ol" {...props} />,
  li: ({ node: _node, ...props }) => <li className="markdown-li" {...props} />,
  blockquote: ({ node: _node, ...props }) => (
    <blockquote className="markdown-blockquote" {...props} />
  ),
  hr: ({ node: _node, ...props }) => <hr className="markdown-hr" {...props} />,
  table: ({ node: _node, children, ...props }) => (
    <div className="markdown-table-wrap">
      <table className="markdown-table" {...props}>
        {children}
      </table>
    </div>
  ),
  th: ({ node: _node, ...props }) => <th className="markdown-th" {...props} />,
  td: ({ node: _node, ...props }) => <td className="markdown-td" {...props} />,
  pre: ({ children }) => <>{children}</>,
  code: ({ node: _node, className, children, ...props }) => {
    const lang = codeLanguage(className)
    const raw = String(children).replace(/\n$/, '')
    if (lang || raw.includes('\n')) {
      return (
        <pre className="markdown-pre">
          {lang ? <span className="markdown-code-lang">{lang}</span> : null}
          <code className={className} {...props}>
            {raw}
          </code>
        </pre>
      )
    }
    return (
      <code className="markdown-inline-code" {...props}>
        {children}
      </code>
    )
  },
  a: ({ node: _node, href, children, ...props }) => {
    const external = Boolean(href?.startsWith('http://') || href?.startsWith('https://'))
    return (
      <a
        href={href}
        className="markdown-a"
        {...(external ? { target: '_blank', rel: 'noopener noreferrer' } : {})}
        {...props}
      >
        {children}
      </a>
    )
  },
  img: ({ node: _node, src, alt, ...props }) => (
    <img src={src} alt={alt || ''} loading="lazy" className="markdown-img" {...props} />
  ),
  input: ({ node: _node, type, checked, ...props }) =>
    type === 'checkbox' ? (
      <input
        type="checkbox"
        checked={checked ?? false}
        readOnly
        className="markdown-task"
        {...props}
      />
    ) : null,
  del: ({ node: _node, ...props }) => <del className="markdown-del" {...props} />,
}

export function AssistantMarkdown({ content }: { content: string }) {
  const prepared = useMemo(() => prepareAssistantMarkdown(content), [content])
  return (
    <Markdown
      remarkPlugins={remarkPlugins}
      rehypePlugins={rehypePlugins as never}
      urlTransform={markdownUrlTransform}
      components={components}
    >
      {prepared}
    </Markdown>
  )
}
