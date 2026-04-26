import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Send, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { $api, type FeedMessageResponse } from '@/api/client'

export function Composer({
  replyTo,
  onClearReply,
}: {
  replyTo: FeedMessageResponse | null
  onClearReply: () => void
}) {
  const [body, setBody] = useState('')
  const queryClient = useQueryClient()
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)

  useEffect(() => {
    if (replyTo) textareaRef.current?.focus()
  }, [replyTo])

  const createMessage = $api.useMutation('post', '/messages', {
    onSuccess: () => {
      setBody('')
      onClearReply()
      // The server pushes the new message via WS, but invalidate as a safety net
      // for the moment between request return and WS frame arrival.
      queryClient.invalidateQueries({ queryKey: ['get', '/feed'] })
    },
  })

  const submit = () => {
    const trimmed = body.trim()
    if (!trimmed || createMessage.isPending) return
    createMessage.mutate({
      body: {
        body: trimmed,
        reply_to_message_id: replyTo?.id ?? null,
      },
    })
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
      className="border-t border-border bg-background p-3"
    >
      {replyTo && (
        <div className="mb-2 flex items-start gap-2 rounded-md border border-border bg-muted/40 px-2 py-1.5 text-xs">
          <div className="min-w-0 flex-1">
            <div className="font-medium">
              Replying to {replyTo.author_display_name}
            </div>
            <div className="line-clamp-1 text-muted-foreground">
              {replyTo.body}
            </div>
          </div>
          <button
            type="button"
            onClick={onClearReply}
            className="rounded p-1 text-muted-foreground hover:bg-muted"
            aria-label="Cancel reply"
          >
            <X className="size-3.5" />
          </button>
        </div>
      )}
      <div className="flex items-end gap-2">
        <Textarea
          ref={textareaRef}
          rows={2}
          placeholder="Write something..."
          value={body}
          onChange={(event) => setBody(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              submit()
            }
          }}
          maxLength={4000}
        />
        <Button
          type="submit"
          size="icon"
          disabled={!body.trim() || createMessage.isPending}
          aria-label="Send message"
        >
          <Send className="size-4" />
        </Button>
      </div>
      {createMessage.error && (
        <p className="mt-2 text-xs text-destructive" role="alert">
          Could not send message.
        </p>
      )}
    </form>
  )
}
