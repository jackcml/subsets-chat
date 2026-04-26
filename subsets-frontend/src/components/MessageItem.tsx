import { Reply } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { FeedMessageResponse } from '@/api/client'

function formatTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

export function MessageItem({
  message,
  isSelf,
  onReply,
}: {
  message: FeedMessageResponse
  isSelf: boolean
  onReply: (message: FeedMessageResponse) => void
}) {
  return (
    <article className="group flex flex-col gap-1.5 rounded-lg border border-transparent px-3 py-2 hover:border-border hover:bg-muted/40">
      <header className="flex items-baseline gap-2">
        <span className="text-sm font-semibold">
          {message.author_display_name}
          {isSelf && (
            <span className="ml-1 text-xs font-normal text-muted-foreground">
              (you)
            </span>
          )}
        </span>
        <span className="text-xs text-muted-foreground">
          {formatTime(message.created_at)}
        </span>
      </header>
      {message.reply_to && (
        <blockquote className="border-l-2 border-border bg-muted/40 px-2 py-1 text-xs text-muted-foreground">
          <span className="font-medium">{message.reply_to.author_display_name}</span>
          <span className="mx-1">·</span>
          <span className="line-clamp-2 whitespace-pre-wrap">
            {message.reply_to.body}
          </span>
        </blockquote>
      )}
      <p className="whitespace-pre-wrap text-sm leading-relaxed">{message.body}</p>
      <div className="opacity-0 transition-opacity group-hover:opacity-100">
        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-2 text-xs"
          onClick={() => onReply(message)}
        >
          <Reply className="size-3.5" />
          Reply
        </Button>
      </div>
    </article>
  )
}
