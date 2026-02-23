import { useReducer } from 'react'
import {
  QuestionState,
  QuestionEvent,
  QuestionTask,
  QuestionLogEntry,
  QuestionResult,
  QuestionFailure,
  QuestionFocus,
} from '../types/question'

export const initialQuestionState: QuestionState = {
  global: {
    stage: 'idle',
    startTime: 0,
    totalQuestions: 0,
    completedQuestions: 0,
    failedQuestions: 0,
    extendedQuestions: 0,
  },
  planning: {
    topic: '',
    difficulty: '',
    questionType: '',
    queries: [],
    progress: '',
  },
  tasks: {},
  activeTaskIds: [],
  results: [],
  failures: [],
  subFocuses: [],
  logs: [],
}

// Helper to create a log entry
const createLog = (content: string, type: QuestionLogEntry['type'] = 'info'): QuestionLogEntry => ({
  id: Math.random().toString(36).substring(7),
  timestamp: Date.now(),
  type,
  content,
})

// Helper to ensure a task exists in state
const ensureTask = (state: QuestionState, taskId: string, focus: string = ''): QuestionTask => {
  if (state.tasks[taskId]) {
    return state.tasks[taskId]
  }
  return {
    id: taskId,
    focus: focus,
    status: 'pending',
    round: 0,
    lastUpdate: Date.now(),
  }
}

export const questionReducer = (state: QuestionState, event: QuestionEvent): QuestionState => {
  // Common log handling
  const newLog = event.type === 'log' ? createLog(event.content || '') : null
  const logs = newLog ? [...state.logs, newLog] : state.logs

  switch (event.type) {
    // --- Progress events (from backend) ---
    case 'progress': {
      const stage = event.stage as QuestionState['global']['stage']
      const status = event.status || ''

      // Planning stage
      if (stage === 'planning') {
        if (status === 'splitting_queries') {
          return {
            ...state,
            global: {
              ...state.global,
              stage: 'planning',
              startTime: state.global.startTime || Date.now(),
              totalQuestions: event.total || state.global.totalQuestions,
            },
            planning: {
              ...state.planning,
              progress: 'Splitting into search queries...',
            },
            logs: [...logs, createLog('Planning started - splitting queries')],
          }
        }
        if (status === 'planning_focuses') {
          return {
            ...state,
            planning: {
              ...state.planning,
              progress: 'Planning sub-focuses for each question...',
            },
            logs: [...logs, createLog('Planning sub-focuses')],
          }
        }
      }

      // Researching stage
      if (stage === 'researching') {
        return {
          ...state,
          global: {
            ...state.global,
            stage: 'researching',
          },
          planning: {
            ...state.planning,
            queries: event.queries || state.planning.queries,
            progress: 'Retrieving knowledge from database...',
          },
          logs: [...logs, createLog('Researching knowledge base')],
        }
      }

      // Generating stage
      if (stage === 'generating') {
        const focuses = event.focuses || event.sub_focuses || []
        const newTasks: Record<string, QuestionTask> = {}

        // Initialize tasks from focuses
        if (focuses.length > 0) {
          focuses.forEach((f: QuestionFocus) => {
            newTasks[f.id] = {
              id: f.id,
              focus: f.focus,
              scenarioHint: f.scenario_hint,
              status: 'pending',
              lastUpdate: Date.now(),
            }
          })
        }

        return {
          ...state,
          global: {
            ...state.global,
            stage: 'generating',
            totalQuestions: event.total || focuses.length || state.global.totalQuestions,
          },
          subFocuses: focuses.length > 0 ? focuses : state.subFocuses,
          tasks: focuses.length > 0 ? newTasks : state.tasks,
          logs: [
            ...logs,
            createLog(`Starting parallel generation of ${event.total || focuses.length} questions`),
          ],
        }
      }

      // Complete stage
      if (stage === 'complete') {
        return {
          ...state,
          global: {
            ...state.global,
            stage: 'complete',
            completedQuestions: event.completed || state.global.completedQuestions,
            failedQuestions: event.failed || state.global.failedQuestions,
          },
          logs: [...logs, createLog('Generation completed', 'success')],
        }
      }

      return state
    }

    // --- Question-specific update ---
    case 'question_update': {
      const questionId = event.question_id
      if (!questionId) return state

      const focusString = typeof event.focus === 'string' ? event.focus : event.focus?.focus || ''
      const existingTask = state.tasks[questionId] || ensureTask(state, questionId, focusString)

      const statusMap: Record<string, QuestionTask['status']> = {
        generating: 'generating',
        validating: 'validating',
        done: 'done',
        error: 'error',
      }

      const newStatus = statusMap[event.status || ''] || existingTask.status

      // Track active tasks
      let activeTaskIds = [...state.activeTaskIds]
      if (newStatus === 'generating' || newStatus === 'validating') {
        if (!activeTaskIds.includes(questionId)) {
          activeTaskIds.push(questionId)
        }
      } else if (newStatus === 'done' || newStatus === 'error') {
        activeTaskIds = activeTaskIds.filter(id => id !== questionId)
      }

      return {
        ...state,
        tasks: {
          ...state.tasks,
          [questionId]: {
            ...existingTask,
            status: newStatus,
            round: event.round || existingTask.round,
            focus: focusString || existingTask.focus,
            lastUpdate: Date.now(),
          },
        },
        activeTaskIds,
      }
    }

    // --- Result received ---
    case 'result':
    case 'question_result': {
      const questionId = event.question_id || `q_${(event.index || 0) + 1}`
      const isExtended = event.extended || event.validation?.decision === 'extended'
      const result: QuestionResult = {
        success: true,
        question_id: questionId,
        question: event.question || {
          question: '',
          correct_answer: '',
          explanation: '',
        },
        validation: event.validation || {},
        rounds: event.rounds || 1,
        focus: event.focus,
        extended: isExtended,
      }

      const existingTask = state.tasks[questionId]

      return {
        ...state,
        tasks: {
          ...state.tasks,
          [questionId]: {
            ...(existingTask || ensureTask(state, questionId)),
            status: 'done',
            result,
            extended: isExtended,
            lastUpdate: Date.now(),
          },
        },
        activeTaskIds: state.activeTaskIds.filter(id => id !== questionId),
        results: [...state.results, result],
        global: {
          ...state.global,
          completedQuestions: state.global.completedQuestions + 1,
          extendedQuestions: state.global.extendedQuestions + (isExtended ? 1 : 0),
        },
        logs: [
          ...logs,
          createLog(
            `Question ${questionId} ${isExtended ? 'extended' : 'generated successfully'} (${result.rounds} rounds)`,
            isExtended ? 'warning' : 'success'
          ),
        ],
      }
    }

    // --- Question error ---
    case 'question_error': {
      const questionId = event.question_id || 'unknown'
      const failure: QuestionFailure = {
        question_id: questionId,
        error: event.error || event.content || 'Unknown error',
        reason: event.reason,
      }

      const existingTask = state.tasks[questionId]

      return {
        ...state,
        tasks: {
          ...state.tasks,
          [questionId]: {
            ...(existingTask || ensureTask(state, questionId)),
            status: 'error',
            error: failure.error,
            lastUpdate: Date.now(),
          },
        },
        activeTaskIds: state.activeTaskIds.filter(id => id !== questionId),
        failures: [...state.failures, failure],
        global: {
          ...state.global,
          failedQuestions: state.global.failedQuestions + 1,
        },
        logs: [...logs, createLog(`Question ${questionId} failed: ${failure.error}`, 'error')],
      }
    }

    // --- Batch summary ---
    case 'batch_summary': {
      return {
        ...state,
        global: {
          ...state.global,
          totalQuestions: event.requested || state.global.totalQuestions,
          completedQuestions: event.completed || state.global.completedQuestions,
          failedQuestions: event.failed || state.global.failedQuestions,
        },
        subFocuses: event.sub_focuses || state.subFocuses,
        logs: [
          ...logs,
          createLog(
            `Batch summary: ${event.completed}/${event.requested} completed, ${event.failed} failed`
          ),
        ],
      }
    }

    // --- Status updates ---
    case 'status': {
      if (event.content === 'started') {
        return {
          ...state,
          global: {
            ...state.global,
            stage: 'planning',
            startTime: Date.now(),
          },
          logs: [...logs, createLog('Question generation started')],
        }
      }
      return state
    }

    case 'agent_status': {
      // Agent status updates (for debugging/display)
      return {
        ...state,
        logs: [
          ...logs,
          createLog(`Agent status update: ${JSON.stringify(event.all_agents)}`, 'system'),
        ],
      }
    }

    case 'token_stats': {
      // Token stats (can be displayed in UI)
      return {
        ...state,
        logs: [...logs, createLog(`Token usage: ${event.stats?.tokens || 0} tokens`, 'system')],
      }
    }

    // --- Complete signal ---
    case 'complete': {
      return {
        ...state,
        global: {
          ...state.global,
          stage: 'complete',
        },
        logs: [...logs, createLog('Question generation completed', 'success')],
      }
    }

    // --- Error ---
    case 'error': {
      return {
        ...state,
        logs: [...logs, createLog(event.content || 'An error occurred', 'error')],
      }
    }

    // --- Log ---
    case 'log': {
      return {
        ...state,
        logs,
      }
    }

    default:
      return { ...state, logs }
  }
}

export const useQuestionReducer = () => {
  return useReducer(questionReducer, initialQuestionState)
}

// Reset helper
export const resetQuestionState = (): QuestionState => ({
  ...initialQuestionState,
  logs: [],
})
