import { GeogebraTabProvider } from '@/context/GeogebraTabContext'
import { QuizFollowupProvider } from '@/context/QuizFollowupContext'

/** Chat, reading and watching state are inherited from the workspace layout. */
export default function MasteryStudyLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <QuizFollowupProvider>
      <GeogebraTabProvider>{children}</GeogebraTabProvider>
    </QuizFollowupProvider>
  )
}
