import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { WatchingPane } from "@/components/watching/WatchingPane";
const api = vi.hoisted(() => ({ listVideoNotes: vi.fn(), createVideoNote: vi.fn(), updateVideoNote: vi.fn(), deleteVideoNote: vi.fn(), saveVideoProgress: vi.fn().mockResolvedValue(undefined) }));
vi.mock("@/lib/video-learning-api", () => api);
const state = vi.hoisted(() => ({ material: null as any, onTime: null as any }));
const noop = () => {};
vi.mock("@/context/WatchingContext", () => ({ useWatching: () => ({ material: state.material, setActive: noop, reportTime: noop }) }));
const t = (key: string, args?: Record<string, string>) => key.replace(/{{(\w+)}}/g, (_, k) => args?.[k] ?? k);
vi.mock("react-i18next", () => ({ useTranslation: () => ({t}) }));
vi.mock("@/components/watching/WatchingPlayer", () => ({ WatchingPlayer: (props: any) => { state.onTime = props.onTime; return <div data-testid="player" />; } }));
vi.mock("@/components/watching/WatchingCaptions", () => ({ WatchingCaptions: () => null }));
vi.mock("@/components/watching/useTranscriptFollow", () => ({useTranscriptFollow: () => {}}));
function material(id: string) { return {material_id:id, source:{url:'video',video_id:'test'},playback:{provider:'youtube'},learning:{marks:[]},metadata:{duration_seconds:600},transcript:{status:'ready',cues:[]}}; }
const saved = {note_id:'n1',notebook_id:'book',material_id:'a',time_seconds:10,body:'My note',created_at:1};
async function open() { render(<WatchingPane onClose={noop}/>); fireEvent.click(screen.getByRole('tab',{name:'Video notes'})); await waitFor(()=>expect(screen.queryByText('Loading notes.')).not.toBeInTheDocument()); }
function draft() { return screen.getByRole('textbox',{name:'Video note'}); }
beforeEach(()=> { vi.clearAllMocks(); state.material=material('a');api.listVideoNotes.mockResolvedValue([]);api.createVideoNote.mockResolvedValue(saved);api.updateVideoNote.mockResolvedValue({...saved,body:'Edited'});api.deleteVideoNote.mockResolvedValue(undefined); });
describe('Watching note reliability',()=>{
 it('anchors typing time across playback and panel changes',async()=>{
  await open(); act(()=>state.onTime(10,600)); fireEvent.change(draft(),{target:{value:'My note'}});
  act(()=>state.onTime(50,600)); fireEvent.click(screen.getByRole('tab',{name:'Transcript'}));fireEvent.click(screen.getByRole('tab',{name:'Video notes'}));
  expect(screen.getByText('Note timestamp: 0:10')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Add video note'}));await screen.findByText('Note saved.');expect(api.createVideoNote).toHaveBeenCalledWith('a','My note',10);
 });
 it('preserves a failed draft and retries at the original time',async()=>{
  api.createVideoNote.mockRejectedValueOnce(new Error('Offline'));await open();act(()=>state.onTime(10,600));fireEvent.change(draft(),{target:{value:'My note'}});
  fireEvent.click(screen.getByRole('button',{name:'Add video note'}));await screen.findByText('Offline');expect(draft()).toHaveValue('My note');act(()=>state.onTime(60,600));
  fireEvent.click(screen.getByRole('button',{name:'Add video note'}));await screen.findByText('Note saved.');expect(api.createVideoNote).toHaveBeenLastCalledWith('a','My note',10);
 });
 it('blocks duplicate writes and typing during save',async()=>{
  let finish!: (value: any)=>void;api.createVideoNote.mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve}));await open();fireEvent.change(draft(),{target:{value:'My note'}});
  const button=screen.getByRole('button',{name:'Add video note'});fireEvent.click(button);fireEvent.click(button);expect(api.createVideoNote).toHaveBeenCalledTimes(1);expect(draft()).toBeDisabled();await act(async()=>finish(saved));
 });
 it('drops an old save when switching away and back to the same material',async()=>{
  let finish!: (value:any)=>void;api.createVideoNote.mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve}));const view=render(<WatchingPane onClose={noop}/>);fireEvent.click(screen.getByRole('tab',{name:'Video notes'}));await waitFor(()=>expect(screen.queryByText('Loading notes.')).not.toBeInTheDocument());fireEvent.change(draft(),{target:{value:'Old'}});fireEvent.click(screen.getByRole('button',{name:'Add video note'}));
  state.material=material('b');view.rerender(<WatchingPane onClose={noop}/>);state.material=material('a');view.rerender(<WatchingPane onClose={noop}/>);await act(async()=>finish(saved));expect(screen.queryByText('My note')).not.toBeInTheDocument();expect(draft()).toHaveValue('');
 });
 it('reloads a failed list without clearing the draft',async()=>{
  api.listVideoNotes.mockRejectedValueOnce(new Error('List offline'));await open();fireEvent.change(draft(),{target:{value:'Keep this'}});fireEvent.click(screen.getByRole('button',{name:'Reload notes'}));await waitFor(()=>expect(screen.queryByText('List offline')).not.toBeInTheDocument());expect(draft()).toHaveValue('Keep this');
 });
 it('edits and deletes saved notes with feedback',async()=>{
  api.listVideoNotes.mockResolvedValue([saved]);await open();fireEvent.click(screen.getByRole('button',{name:'Edit note at 0:10'}));fireEvent.change(screen.getByRole('textbox',{name:'Edit note at 0:10'}),{target:{value:'Edited'}});fireEvent.click(screen.getByRole('button',{name:'Save video note'}));await screen.findByText('Edited');expect(api.updateVideoNote).toHaveBeenCalledWith('a','n1','Edited');fireEvent.click(screen.getByRole('button',{name:'Delete note at 0:10'}));fireEvent.click(screen.getByRole('button',{name:'Delete'}));await screen.findByText('Note deleted.');expect(api.deleteVideoNote).toHaveBeenCalledWith('a','n1');
 });
});
