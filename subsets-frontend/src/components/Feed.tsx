import { useEffect, useRef } from 'react'
import { $api, type FeedMessageResponse } from '@/api/client'
import { useAuth } from '@/auth/useAuth'
import { MessageItem } from './MessageItem'

export function Feed({
  onReply,
}: {
  onReply: (message: FeedMessageResponse) => void
}) {
  const { user } = useAuth()
  const feedQuery = $api.useQuery('get', '/feed')
  const bottomRef = useRef<HTMLDivElement | null>(null)

  const messages = feedQuery.data ?? []
  const lastMessageId = messages[messages.length - 1]?.id

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [lastMessageId])

  if (feedQuery.isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
        Loading feed...
      </div>
    )
  }

  if (feedQuery.error) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-destructive">
        Could not load feed.
      </div>
    )
  }

  if (messages.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center px-6 text-center text-sm text-muted-foreground">
        Your feed is empty. Add people to your set, then post or wait for them
        to.
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto px-3 py-3">
      <div className="mx-auto flex max-w-2xl flex-col gap-1">
        {messages.map((message) => (
          <MessageItem
            key={message.id}
            message={message}
            isSelf={message.author_user_id === user?.id}
            onReply={onReply}
          />
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
