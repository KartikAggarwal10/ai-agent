import asyncio
import base64
import json
from datetime import datetime
import websockets
HOST = "localhost"
PORT = 8765
# Keep track of connected browser clients so we can push a
# "take a screenshot now" request to them at any time.
# The most recently received screenshot (raw bytes). An LLM-driven
# piece of code elsewhere in your app can just read this whenever it wants.
class helper:
    def __init__(self):
        self.connected_clients = set()
        self.latest_screenshot = None
        self.stored_credentials = {}


    
    async def send_message(self, message_type: str, data):
        if not self.connected_clients:
            print("No connected clients")
            return

        print(f"[DEBUG] send_message type={message_type} data_type={type(data)} data={data}")
        message = json.dumps({
            "type": message_type,
            "data": data
        })

        await asyncio.gather(
            *(client.send(message) for client in self.connected_clients)
        )


    async def handler(self,websocket):
        self.connected_clients.add(websocket)
        print(f"Client connected. Total clients: {len(self.connected_clients)}")
        try:
            async for message in websocket:
                data = json.loads(message)
                
                if data.get("type") == "hello":
                    creds = data.get("credentials")
                    if creds:
                        self.stored_credentials = creds
                        print(f"[INFO] Received credentials from frontend: {list(creds.keys())}")
                    else:
                        print("[INFO] No credentials received from frontend at startup.")

                elif data.get("type") == "init_credentials":
                    self.stored_credentials = data.get("credentials", {})
                    print(f"[INFO] Updated stored credentials: {self.stored_credentials}")

                elif data.get("type") == "screenshot":
                    await self.handle_screenshot(data["image"])
                elif data.get("type") == "user_interrupt_response":
                    user_payload = data.get("payload")
                    print("Received response from frontend:", user_payload)
                    # Resume graph with the payload
                    from langraph_agent import builder
                    from langgraph.types import Command
                    # Reuse the cached graph so the SAME MemorySaver instance
                    # is always used – avoids Task/ToolStep deserialization errors.
                    if not hasattr(self, "_graph") or self._graph is None:
                        self._graph = builder()
                    graph = self._graph
                    config = {"configurable": {"thread_id": "session_1"}}
                    
                    async for event in graph.astream(Command(resume=user_payload), config=config, stream_mode="updates"):
                        if "__interrupt__" in event:
                            interrupt_payload = event["__interrupt__"][0].value
                            await self.send_message("graph_interrupt", interrupt_payload)
                            break
                elif data.get("type") == "question":
                    question = data.get("question", "")
                    email = data.get("email")
                    user_name = data.get("user_name")
                    print("Question received:", question[:80] if question else "")

                    # -------------------------------------------------------------
                    # Check if user sent pasted data with more than 20 lines
                    # If so, activate embeddings pipeline just like embeddings.py
                    # -------------------------------------------------------------
                    from embedding_service import embedding_service, is_more_than_20_lines

                    if question and is_more_than_20_lines(question):
                        line_count = len(question.strip().splitlines())
                        print(f"[INFO] Pasted data with {line_count} lines (>20) detected! Executing embeddings pipeline (embeddings.py)...")

                        await self.send_message(
                            "procedure",
                            f"Embeddings Pipeline Activated\n"
                            f"Detected {line_count} lines of pasted text (> 20 lines).\n"
                            f"Chunking with RecursiveCharacterTextSplitter, indexing into FAISS vectorstore, "
                            f"and running Hybrid Retrieval (FAISS + BM25 + CrossEncoder Reranker)..."
                        )

                        loop = asyncio.get_running_loop()
                        result = await loop.run_in_executor(
                            None,
                            embedding_service.process_pasted_data,
                            question
                        )

                        formatted_output = (
                            f"📄 Embeddings Processing Complete:\n"
                            f"• Total Chunks Created & Indexed: {result['chunk_count']}\n"
                            f"• Formulated Query: \"{result['query']}\"\n"
                            f"• Context Chunks Retrieved: {result['retrieved_count']}\n\n"
                            f"🤖 Assistant Answer (Strictly Context-Based):\n"
                            f"{result['answer']}"
                        )
                        await self.send_message("result", formatted_output)
                        continue

                    await self.start_graph({
                        "user_name": user_name,
                        "email": email,
                        "question": question,
                        "tasks": [],
                        "result": {},
                        "previous_content_needed": [],
                        "need_img": False,
                        # Pass stored credentials into LangGraph State
                        "social_media_user_name": self.stored_credentials.get("social_media_user_name", ""),
                        "social_media_password": self.stored_credentials.get("social_media_password", ""),
                        "ecommerce_user_name": self.stored_credentials.get("ecommerce_user_name", ""),
                        "ecommerce_password": self.stored_credentials.get("ecommerce_password", ""),
                    })
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.connected_clients.discard(websocket)
            print(f"Client disconnected. Total clients: {len(self.connected_clients)}")


    async def handle_screenshot(self,image_data_url: str):
        """image_data_url looks like: data:image/png;base64,AAAA..."""
        if "," in image_data_url:
            image_data_url = image_data_url.split(",", 1)[1]

        image_bytes = base64.b64decode(image_data_url)
        self.latest_screenshot = image_bytes

        # filename = f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        # with open(filename, "wb") as f:
        #     f.write(image_bytes)

        # print(f"Received screenshot -> saved as {filename}")

        return image_bytes

        # ---- Hand off to your LLM here ----
        # e.g. send `image_bytes` (or `filename`) into your model call.


    async def request_screenshot(self):
        """
        Call this from ANYWHERE in your Python code whenever the LLM decides
        it wants a fresh look at the screen. Every connected browser tab will
        immediately capture a frame and send it back over the same socket.
        """
        if not self.connected_clients:
            print("No connected clients to request a screenshot from")
            return
        message = json.dumps({"type": "capture_request"})
        await asyncio.gather(*(client.send(message) for client in self.connected_clients))


    async def start_graph(self, initial_input):
        from langraph_agent import builder
        # Always reuse the same compiled graph / MemorySaver instance.
        if not hasattr(self, "_graph") or self._graph is None:
            self._graph = builder()
        graph = self._graph
        config = {"configurable": {"thread_id": "session_1"}}
        print("Starting graph...")
        async for event in graph.astream(initial_input, config=config, stream_mode="updates"):
            if "__interrupt__" in event:
                interrupt_payload = event["__interrupt__"][0].value
                print("Graph interrupted! Sending to frontend:", interrupt_payload)
                await self.send_message("graph_interrupt", interrupt_payload)
                break
            else:
                print("Graph update:", event)

    async def demo_trigger_loop(self):
        """
        Simple demo: type 'capture' + Enter in this terminal to trigger a
        screenshot request. Replace this with wherever your LLM logic lives
        (e.g. call `await request_screenshot()` inside a tool call handler).
        """
        loop = asyncio.get_event_loop()
        while True:
            line = await loop.run_in_executor(None, input, "")
            if line.strip().lower() == "capture":
                await self.request_screenshot()
            elif line.strip().lower() == "start":
                await self.start_graph({"tasks": []})


    async def main(self):
        async with websockets.serve(self.handler, HOST, PORT):
            print(f"WebSocket server running on ws://{HOST}:{PORT}")
            print("Type 'capture' + Enter to request a screenshot from connected browsers.")
            await self.demo_trigger_loop()

