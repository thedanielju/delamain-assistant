'use client'

import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import rehypeHighlight from 'rehype-highlight'
import { cn } from '@/lib/utils'
import type { ChatMessage } from '@/lib/types'

interface CodeBlockProps {
  language?: string
  children: string
}

function CodeBlock({ language, children }: CodeBlockProps) {
  return (
    <div className="relative my-2 rounded-md overflow-hidden border border-white/[0.08]">
      {language && (
        <div className="flex items-center justify-between px-3 py-1 bg-[#111111] border-b border-white/[0.08]">
          <span className="text-[10px] font-mono text-[#888888]">{language}</span>
        </div>
      )}
      <pre className="overflow-x-auto bg-[#0d0d0d] p-3 m-0">
        <code
          className={cn('text-[0.78rem] leading-relaxed font-mono text-[#d4d4d4]', language && `language-${language}`)}
        >
          {children}
        </code>
      </pre>
    </div>
  )
}

interface MessageBubbleProps {
  message: ChatMessage
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === 'user'

  if (isUser) {
    return (
      <div className="flex justify-end w-full">
        <div className="max-w-[80%] md:max-w-[65%] bg-[#111111] rounded-2xl rounded-tr-sm px-4 py-2.5">
          <p className="text-white text-sm leading-relaxed font-sans whitespace-pre-wrap break-words">
            {message.content}
          </p>
        </div>
      </div>
    )
  }

  // Assistant message
  return (
    <div className="flex justify-start w-full">
      <div className={cn('max-w-[90%] md:max-w-[80%] assistant-prose', message.streaming && 'streaming-cursor')}>
        <ReactMarkdown
          remarkPlugins={[remarkGfm, remarkMath]}
          rehypePlugins={[rehypeKatex, rehypeHighlight]}
          components={{
            // Override code to use our CodeBlock for fenced blocks
            code({ className, children, ...props }) {
              const match = /language-(\w+)/.exec(className || '')
              const isInline = !match && !className
              if (isInline) {
                return (
                  <code className="bg-[#1a1a1a] text-[#7ec8a0] px-1.5 py-0.5 rounded text-[0.8em] font-mono" {...props}>
                    {children}
                  </code>
                )
              }
              return (
                <CodeBlock language={match?.[1]}>
                  {String(children).replace(/\n$/, '')}
                </CodeBlock>
              )
            },
            pre({ children }) {
              // Let CodeBlock handle the pre tag wrapping
              return <>{children}</>
            },
            a({ href, children }) {
              return (
                <a
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[#7eb8da] underline underline-offset-2 hover:text-white transition-colors"
                >
                  {children}
                </a>
              )
            },
          }}
        >
          {message.content}
        </ReactMarkdown>
      </div>
    </div>
  )
}
