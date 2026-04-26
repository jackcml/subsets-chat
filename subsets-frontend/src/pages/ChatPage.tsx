import { useState } from 'react'
import { AppLayout } from '@/components/AppLayout'
import { Composer } from '@/components/Composer'
import { Feed } from '@/components/Feed'
import { UserList } from '@/components/UserList'
import { getStoredToken, type FeedMessageResponse } from '@/api/client'
import { useFeedSocket } from '@/ws/useFeedSocket'

export function ChatPage() {
  const [replyTo, setReplyTo] = useState<FeedMessageResponse | null>(null)
  useFeedSocket(getStoredToken())

  return (
    <AppLayout sidebar={<UserList />}>
      <Feed onReply={setReplyTo} />
      <Composer replyTo={replyTo} onClearReply={() => setReplyTo(null)} />
    </AppLayout>
  )
}
