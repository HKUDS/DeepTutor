# Web Frontend

The Web frontend is a Next.js 16 application that provides the user interface for the DeepTutor system.

## 📋 Overview

The frontend provides:

- Dashboard with activity tracking
- Knowledge base management
- Problem solving interface
- Question generation interface
- Research interface
- Guided learning interface
- Co-Writer interface
- Notebook management
- Idea generation interface

## 🏗️ Architecture

```
web/
├── app/                      # Next.js app directory
│   ├── page.tsx             # Dashboard (home page)
│   ├── layout.tsx            # Root layout
│   ├── globals.css           # Global styles
│   ├── knowledge/            # Knowledge base pages
│   ├── solver/               # Problem solving pages
│   ├── question/             # Question generation pages
│   ├── research/             # Research pages
│   ├── guide/                # Guided learning pages
│   ├── co_writer/            # Co-Writer pages
│   ├── notebook/             # Notebook pages
│   ├── ideagen/              # Idea generation pages
│   └── settings/             # Settings pages
├── components/               # React components
│   ├── Sidebar.tsx           # Navigation sidebar
│   ├── SystemStatus.tsx      # System status indicator
│   ├── ActivityDetail.tsx    # Activity detail view
│   ├── CoWriterEditor.tsx    # Co-Writer editor
│   ├── AddToNotebookModal.tsx # Add to notebook modal
│   └── ui/                   # UI components
│       ├── Button.tsx
│       └── Modal.tsx
├── context/                  # React context
│   └── GlobalContext.tsx     # Global state management
├── lib/                      # Utilities
│   └── api.ts                # API client
├── package.json              # Dependencies
├── tsconfig.json             # TypeScript configuration
├── tailwind.config.js        # Tailwind CSS configuration
└── postcss.config.js         # PostCSS configuration
```

## 🛠️ Technology Stack

- **Framework**: Next.js 16 (App Router + Turbopack)
- **Runtime**: React 19
- **Language**: TypeScript
- **Styling**: Tailwind CSS
- **UI Components**: Custom components with Lucide React icons
- **Markdown**: react-markdown with KaTeX for math
- **PDF Export**: jsPDF + html2canvas
- **Animations**: Framer Motion 11

## 📦 Dependencies

### Core Dependencies

```json
{
  "next": "^16.1.1",
  "react": "^19.0.0",
  "react-dom": "^19.0.0",
  "react-markdown": "^9.0.1",
  "rehype-katex": "^7.0.1",
  "remark-math": "^6.0.0",
  "lucide-react": "^0.460.0",
  "framer-motion": "^11.15.0",
  "jspdf": "^2.5.2",
  "html2canvas": "^1.4.1"
}
```

## 🚀 Getting Started

### Installation

```bash
cd web
npm install
```

### Development

```bash
npm run dev
```

This uses **Turbopack** by default for faster development builds.

The frontend will be available at `http://localhost:3782` (or port configured in `config/main.yaml`).

### Build

```bash
npm run build
npm start
```

## 📁 Key Components

### Dashboard (app/page.tsx)

Main dashboard showing:

- Recent activities
- Knowledge base overview
- Notebook statistics
- Quick access to modules

### API Client (lib/api.ts)

Centralized API client for backend communication:

```typescript
import { apiUrl } from "@/lib/api";

// REST API
const response = await fetch(`${apiUrl}/knowledge/list`);

// WebSocket
const ws = new WebSocket(`${wsUrl}/api/v1/solve`);
```

### Global Context (context/GlobalContext.tsx)

Manages global state:

- System status
- User preferences
- Active sessions

### Sidebar (components/Sidebar.tsx)

Navigation sidebar with links to all modules.

## 🔌 API Integration

### REST API

```typescript
const response = await fetch(`${apiUrl}/api/v1/knowledge/list`, {
  method: "GET",
  headers: {
    "Content-Type": "application/json",
  },
});
const data = await response.json();
```

### WebSocket

```typescript
const ws = new WebSocket(`${wsUrl}/api/v1/solve`);

ws.onopen = () => {
  ws.send(
    JSON.stringify({
      question: "Your question",
      kb_name: "ai_textbook",
    }),
  );
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  // Handle streaming data
};

ws.onerror = (error) => {
  console.error("WebSocket error:", error);
};

ws.onclose = () => {
  console.log("WebSocket closed");
};
```

## 🎨 Styling

### Tailwind CSS

The project uses Tailwind CSS for styling. Configuration in `tailwind.config.js`.

### Global Styles

Global styles in `app/globals.css` including:

- Base styles
- Custom CSS variables
- Utility classes

## 📱 Pages

### Knowledge Base (`/knowledge`)

- List knowledge bases
- Create new knowledge base
- Upload documents
- View knowledge base details

### Problem Solving (`/solver`)

- Input problem
- Select knowledge base
- Real-time solving with streaming
- View solution

### Question Generation (`/question`)

- Configure question requirements
- Generate questions
- View generated questions

### Research (`/research`)

- Input research topic
- Select research mode
- Real-time research progress
- View research report

### Guided Learning (`/guide`)

- Select notebook
- Generate learning plan
- Interactive learning pages
- Q&A during learning

### Co-Writer (`/co_writer`)

- Markdown editor
- AI text editing
- Automatic annotation
- TTS narration

### Notebook (`/notebook`)

- List notebooks
- Create/edit notebooks
- View notebook records
- Organize records

### Idea Generation (`/ideagen`)

- Select notebook
- Generate research ideas
- View generated ideas

## ⚙️ Configuration

### API Base URL

Configured in `lib/api.ts`:

```typescript
export const apiUrl =
  process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8001";
export const wsUrl = process.env.NEXT_PUBLIC_WS_BASE || "ws://localhost:8001";
```

Set in `.env.local`:

```bash
NEXT_PUBLIC_API_BASE=http://localhost:8001
NEXT_PUBLIC_WS_BASE=ws://localhost:8001
```

### Next.js Configuration

Key settings in `next.config.js`:

```javascript
const nextConfig = {
  // Dev indicator position
  devIndicators: {
    position: "bottom-right",
  },
  // Turbopack configuration
  turbopack: {
    resolveAlias: {
      cytoscape: "cytoscape/dist/cytoscape.cjs.js",
    },
  },
  // Transpile packages
  transpilePackages: ["mermaid"],
};
```

## 🔗 Related Modules

- **Backend API**: `src/api/` - FastAPI backend
- **Agents**: `src/agents/` - Agent implementations
- **Config**: `config/` - Configuration files

## 🛠️ Development

### Adding a New Page

1. Create page in `app/`:

   ```typescript
   // app/my-page/page.tsx
   export default function MyPage() {
     return <div>My Page</div>
   }
   ```

2. Add navigation link in `components/Sidebar.tsx`

### Adding a New Component

1. Create component in `components/`:

   ```typescript
   // components/MyComponent.tsx
   export default function MyComponent() {
     return <div>My Component</div>
   }
   ```

2. Export from `components/index.ts` if needed

### Styling Guidelines

- Use Tailwind CSS utility classes
- Follow existing component patterns
- Use Lucide React for icons
- Maintain responsive design

## ⚠️ Notes

1. **API URL**: Ensure API base URL matches backend configuration
2. **WebSocket**: WebSocket URL should use `wss://` for secure production environments (fallback to `ws://` for local development only)
3. **CORS**: Backend must allow frontend origin in CORS settings
4. **Environment Variables**: Use `NEXT_PUBLIC_` prefix for client-side variables
5. **Turbopack**: Development mode uses Turbopack by default for faster builds
