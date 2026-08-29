import ReactMarkdown, { type Components } from 'react-markdown'
import remarkBreaks from 'remark-breaks'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import { CodeBlock, JsonBlock } from './CodeBlock'
import { hastLang, hastText, looksLikeJson } from '../../lib/codeUtils'

interface MarkdownContentProps {
  content: string
}

const components: Components = {
  // Fenced code → highlighted block with a language label + copy button.
  pre: ({ node, children }) => (
    <CodeBlock raw={hastText(node)} lang={hastLang(node)}>
      {children}
    </CodeBlock>
  ),
  // A paragraph that is exactly one JSON value → collapsible JSON card.
  p: ({ node, children }) => {
    const text = hastText(node)
    if (looksLikeJson(text)) return <JsonBlock text={text} />
    return <p>{children}</p>
  },
}

export function MarkdownContent({ content }: MarkdownContentProps) {
  return (
    <div className="md-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkBreaks]}
        rehypePlugins={[[rehypeHighlight, { detect: true, ignoreMissing: true }]]}
        components={components}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}
