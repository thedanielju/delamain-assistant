'use client'

import { useEffect, useRef } from 'react'
import { MessageBubble } from './MessageBubble'
import { ToolCallCard } from './ToolCallCard'
import type { ChatMessage } from '@/lib/types'

interface ChatPaneProps {
  messages: ChatMessage[]
}

export function ChatPane({ messages }: ChatPaneProps) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  return (
    <div className="flex-1 overflow-y-auto px-3 md:px-6 py-4">
      <div className="max-w-3xl mx-auto flex flex-col gap-5">
        {messages.map((message) => (
          <div key={message.id} className="flex flex-col gap-2">
            {/* Tool calls rendered BEFORE this message */}
            {message.toolCallsBefore && message.toolCallsBefore.length > 0 && (
              <div className="flex flex-col gap-1.5">
                {message.toolCallsBefore.map((tool) => (
                  <ToolCallCard
                    key={tool.id}
                    tool={tool}
                    defaultExpanded={tool.expanded ?? false}
                  />
                ))}
              </div>
            )}
            <MessageBubble message={message} />
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
