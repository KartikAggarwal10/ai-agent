import { useRef, useState, useEffect, useCallback } from "react";
// add mike, speak button ui better, avatar attach, human in the loop for display post, in display post correct issue of password
const WS_URL = "ws://localhost:8765";

export default function Display({ userName, email }) {
    const videoRef = useRef(null);
    const wsRef = useRef(null);

    const [img, setImg] = useState(null);
    const [connected, setConnected] = useState(false);
    const [question, setQuestion] = useState("");
    const [messages, setMessages] = useState([]);
    const [interupts, setInterrupts] = useState([]);
    const [result_of_interupts, setInterruptsResults] = useState({});

    // Capture screenshot and send it to Python
    const captureAndSend = useCallback(async () => {
        if (!videoRef.current || !videoRef.current.videoWidth) {
            console.warn("Video not ready for capture yet");
            return;
        }

        const canvas = document.createElement("canvas");
        canvas.width = videoRef.current.videoWidth;
        canvas.height = videoRef.current.videoHeight;

        const ctx = canvas.getContext("2d");
        ctx.drawImage(videoRef.current, 0, 0, canvas.width, canvas.height);

        const blob = await new Promise((resolve) =>
            canvas.toBlob(resolve, "image/png")
        );

        setImg(blob);

        const reader = new FileReader();
        reader.onloadend = () => {
            const base64data = reader.result;
            if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
                wsRef.current.send(
                    JSON.stringify({ type: "screenshot", image: base64data })
                );
                console.log("Screenshot sent to backend");
            } else {
                console.warn("WebSocket not connected");
            }
        };
        reader.readAsDataURL(blob);
    }, []);

    // WebSocket connection
    useEffect(() => {
        let ws;
        let cancelled = false;
        let reconnectTimer;

        function connect() {
            ws = new WebSocket(WS_URL);
            wsRef.current = ws;

                        ws.onopen = async () => {
                console.log("WebSocket connected");
                setConnected(true);

                // Fetch credentials from DB / localStorage at startup
                const creds = await getStoredCredentials(userName, email);

                // Send hello + credentials to Python
                ws.send(
                    JSON.stringify({
                        type: "hello",
                        state: { user_name: userName, email: email },
                        credentials: creds ? {
                            social_media_user_name: creds.social_media_user_name || "",
                            social_media_password: creds.social_media_password || "",
                            ecommerce_user_name: creds.ecommerce_user_name || "",
                            ecommerce_password: creds.ecommerce_password || "",
                        } : null
                    })
                );
            };
// Search the web for recent news about the Jamui Bihar incident and summarize the key findings.
//Then create a post on my social media with that summary, and also check my latest posts.

            ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    if (data.type === "capture_request") {
                        console.log("Backend requested screenshot");
                        captureAndSend();
                    } else if (data.type === "text") {
                        console.log("----> " + data.data)
                        setMessages((prev) => [...prev, data.data]);
                    }else if (data.type === "procedure" || data.type === "result") {
    console.log("----> " + data.data);
    setMessages((prev) => [...prev, data.data]);
} else if (data.type === "graph_interrupt") {
                        console.log("----> " + data.data)
                        // Backend may send a single interrupt object — normalize to array
                        setInterrupts(Array.isArray(data.data) ? data.data : [data.data]);
                    }
                } catch (e) {
                    console.error("Bad message from backend", e);
                }
            };

            ws.onclose = () => {
                console.log("WebSocket disconnected");
                setConnected(false);
                if (!cancelled) {
                    reconnectTimer = setTimeout(connect, 2000);
                }
            };

            ws.onerror = (err) => {
                console.error("WebSocket error", err);
                ws.close();
            };
        }

        connect();

        return () => {
            cancelled = true;
            clearTimeout(reconnectTimer);
            wsRef.current?.close();
        };
    }, [userName, email, captureAndSend]);

    // Start screen sharing

    // 1. Helper function to check DB / API / localStorage for credentials
async function getStoredCredentials(userName, email) {
    try {
        // Option A: If you have a backend API endpoint that reads from MongoDB:
        // const response = await fetch(`http://localhost:3000/api/get_credentials?user=${encodeURIComponent(userName || email)}`);
        // if (response.ok) return await response.json();

        // Option B: From localStorage (if saved on login/setup):
        const saved = localStorage.getItem("user_credentials");
        if (saved) {
            return JSON.parse(saved);
        }
    } catch (err) {
        console.warn("Could not fetch credentials from DB/storage:", err);
    }
    return null;
}

    async function startScreenShare() {
        try {
            const stream = await navigator.mediaDevices.getDisplayMedia({ video: true });
            videoRef.current.srcObject = stream;
            await videoRef.current.play();
        } catch (error) {
            console.error("Screen sharing failed:", error);
        }
    }

    // Send interrupt response to backend
    function interrupt_res(payload) {
        console.log("sending interrupt response", payload);
        if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
            wsRef.current.send(
                JSON.stringify({
                    type: "user_interrupt_response",
                    payload: payload ?? result_of_interupts,
                })
            );
            setInterrupts([]);
            setInterruptsResults({});
        }
    }

    // Send question to Python backend
    function sendQuestion() {
        if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
            wsRef.current.send(
                JSON.stringify({
                    type: "question",
                    question: question,
                    user_name: userName,
                    email: email,
                })
            );
            console.log("Question sent:", question);
            setQuestion("");
        }
    }

    return (
        <>
            <p>
                Backend:{" "}
                {connected ? "Connected ✅" : "Disconnected ❌"}
            </p>

            <button onClick={startScreenShare}>Share Screen</button>

            <video ref={videoRef} autoPlay playsInline width="800" />

            <button onClick={captureAndSend}>Screenshot (manual)</button>

            {img && (
                <img src={URL.createObjectURL(img)} alt="screenshot" width="500" />
            )}

            <div>
                {messages.map((message, index) => (
                    <p key={index}>{message}</p>
                ))}
            </div>

            <input
                type="text"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="Ask a question..."
            />
            <button onClick={sendQuestion}>Send</button>

            {interupts.map((interrupt, index) => {
                if (interrupt.action === "require_login") {
                    return (
                        <div key={index}>
                            <input
                                type="email"
                                placeholder="Email"
                                
                                onChange={(e) =>
                                    setInterruptsResults((prev) => ({ ...prev, email: e.target.value }))
                                }
                            />
                            <input
                                type="password"
                                placeholder="Password"
                                onChange={(e) =>
                                    setInterruptsResults((prev) => ({ ...prev, password: e.target.value }))
                                }
                            />
                            <button onClick={() => interrupt_res()}>Send</button>
                        </div>
                    );
                }

                if (interrupt.action === "confirm_or_edit_create_order") {
                    return (
                        <ConfirmOrEditOrderPanel
                            key={index}
                            interrupt={interrupt}
                            onSubmit={interrupt_res}
                        />
                    );
                }
                if(interrupt.action === "confirm_or_edit_create_product") {
                    return (
                        <ConfirmOrEditProductPanel key = {index} interrupt={interrupt} onSubmit={interrupt_res} />
                    )
                }
                if(interrupt.action === "verify_email") {
                    return ( <ConfirmEmail key = {index} interrupt={interrupt} onSubmit={interrupt_res} />)
                }
                if(interrupt.action === "preview_post") {
                    return(<ConfirmEditCreatePost key = {index} interrupt={interrupt} onSubmit={interrupt_res}/>)
                }
                if(interrupt.action === "confirm_follow_request") {
                    return(<div>
                        {interrupt.message} <button onClick={() => interrupt_res({"approved" : true})}>yes</button> <button onClick={() => interrupt_res()}>no</button>
                    </div>)
                }
                if (interrupt.action === "verify_plan_readme") {
                    return (
                        <PlanVerificationModal
                            key={index}
                            interrupt={interrupt}
                            onSubmit={interrupt_res}
                        />
                    );
                }
                return null;
            })}
        </>
    );
}

function PlanVerificationModal({ interrupt, onSubmit }) {
    const [feedback, setFeedback] = useState("");
    const [isRevising, setIsRevising] = useState(false);

    const handleApprove = () => {
        onSubmit({ approved: true });
    };

    const handleSuggestChanges = () => {
        if (!feedback.trim()) return;
        onSubmit({
            approved: false,
            feedback: feedback.trim()
        });
        setFeedback("");
        setIsRevising(true);
    };

    return (
        <div style={{
            background: "#1e1e2e",
            color: "#cdd6f4",
            padding: "20px",
            borderRadius: "12px",
            boxShadow: "0 8px 24px rgba(0,0,0,0.5)",
            margin: "15px 0",
            maxWidth: "700px"
        }}>
            <h3 style={{ margin: "0 0 10px", color: "#89b4fa" }}>
                📋 Review Execution Plan & Specifications
            </h3>
            
            {/* Markdown Plan Preview */}
            <div style={{
                background: "#181825",
                padding: "16px",
                borderRadius: "8px",
                maxHeight: "350px",
                overflowY: "auto",
                whiteSpace: "pre-wrap",
                fontFamily: "monospace",
                fontSize: "13px",
                lineHeight: "1.5",
                border: "1px solid #313244"
            }}>
                {interrupt.readme_markdown}
            </div>

            {/* Actions */}
            <div style={{ marginTop: "16px", display: "flex", gap: "10px", alignItems: "center" }}>
                <button
                    onClick={handleApprove}
                    style={{
                        background: "#a6e3a1",
                        color: "#11111b",
                        border: "none",
                        padding: "10px 18px",
                        borderRadius: "6px",
                        fontWeight: "bold",
                        cursor: "pointer"
                    }}
                >
                    ✅ Approve & Execute
                </button>

                <input
                    type="text"
                    placeholder="Suggest changes (e.g. 'Don't email, just summarize')"
                    value={feedback}
                    onChange={(e) => setFeedback(e.target.value)}
                    style={{
                        flex: 1,
                        padding: "10px",
                        borderRadius: "6px",
                        border: "1px solid #45475a",
                        background: "#313244",
                        color: "#fff"
                    }}
                />

                <button
                    onClick={handleSuggestChanges}
                    style={{
                        background: "#f9e2af",
                        color: "#11111b",
                        border: "none",
                        padding: "10px 16px",
                        borderRadius: "6px",
                        fontWeight: "bold",
                        cursor: "pointer"
                    }}
                >
                    🔄 Revise Plan
                </button>
            </div>
        </div>
    );
}
 
function ConfirmEditCreatePost({interrupt,onSubmit}) {
    const raw_data = interrupt.current_params || {}
    const[feedback,setFeedback] = useState("")
    const[title,setTitle] = useState(raw_data.title ?? "")
    const[content,setContent] = useState(raw_data.content ?? "")
    const[tags,setTags] = useState(Array.isArray(raw_data.tags) ? raw_data.tags : [])
    const[category,setCategory] = useState(raw_data.category ?? "")
    const[changetitle,changesetTitle] = useState(false)
    const[changecontent,changesetContent] = useState(false)
    const[changetags,changesetTags] = useState(false)
    const[changecategory,changesetCategory]= useState(false)
    const[addTags,setAddTags] = useState("")
    function handleApprove() {
        const updated_params = {
            title,content,tags,category
        };
        onSubmit({ approved: true, updated_params });
    }
    function handleSendSuggestion() {
        const payload = {};
        const updated_params = {title,content,tags,category};
        payload.approved = false;
        payload.updated_params = updated_params
        payload.feedback = feedback
        onSubmit(payload)
    }
    function handleReject() {
        onSubmit({ approved: false, feedback: "User rejected the post." });
    }
    return(
        <div>
            {interrupt.message}

        {!changetitle &&<span onDoubleClick={() => changesetTitle(true)} >title : {title}</span> }
        {changetitle &&(<div> <input type = "text" value={title} onChange={(e) => setTitle(e.target.value)}/> <button onClick={() => changesetTitle(false)}>done</button> </div>)}
        
        {!changecontent &&<span onDoubleClick={() => changesetContent(true)} >content : {content}</span> }
        {changecontent &&(<div> <input type = "text" value={content} onChange={(e) => setContent(e.target.value)}/> <button onClick={() => changesetContent(false)}>done</button> </div>)}
         {!changetags && (
            <span onDoubleClick={() => changesetTags(true)}>
                tags :
                {tags.map((tag, index) => (
                    <div key={index}>{tag}</div>
                ))}
            </span>
        )}

        {changetags && (
            <div>
                <input
                    type="text"
                    value={addTags}
                    onChange={(e) => setAddTags(e.target.value)}
                />

                <button
                    onClick={() => {
                        if (addTags.trim() === "") return;

                        setTags(prev => [...prev, addTags.trim()]);
                        setAddTags("");
                    }}
                >
                    add tag
                </button>

                {tags.map((tag, index) => (
                    <div key={index}>
                        {tag}

                        <button
                            onClick={() => {
                                setTags(prev =>
                                    prev.filter((_, i) => i !== index)
                                );
                            }}
                        >
                            delete tag
                        </button>
                    </div>
                ))}
            </div>
        )}


        {!changecategory &&<span onDoubleClick={() => changesetCategory(true)} >category : {category}</span> }
        {changecategory &&(<div> <input type = "text" value={category} onChange={(e) => setCategory(e.target.value)}/> <button onClick={() => changesetCategory(false)}>done</button> </div>)}
        
        <div style={{ marginBottom: 14 }}>
                <label
                    style={{ display: "block", marginBottom: 5, fontWeight: 600 }}
                >
                    Suggestion / Feedback{" "}
                    <span
                        style={{ fontWeight: 400, color: "#999", fontSize: 12 }}
                    >
                        (optional — send without typing anything is fine too)
                    </span>
                </label>
                <textarea
                    rows={3}
                    value={feedback}
                    onChange={(e) => setFeedback(e.target.value)}
                    placeholder="e.g. Reduce quantity of item X, swap item Y for Z..."
                    style={{width: "100%",boxSizing: "border-box",borderRadius: 5,border: "1px solid #ccc",padding: "8px 10px",fontSize: 13,resize: "vertical",}}
                />
            </div>

            {/* Action buttons */}
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                <button
                    onClick={handleApprove}
                    style={{ ...btnStyle, background: "#28a745", color: "#fff" }}
                >
                    ✅ Approve Post
                </button>

                <button
                    onClick={handleSendSuggestion}
                    style={{ ...btnStyle, background: "#0070f3", color: "#fff" }}
                >
                    💬 Send Suggestion
                </button>

                <button
                    onClick={handleReject}
                    style={{ ...btnStyle, background: "#dc3545", color: "#fff" }}
                >
                    ❌ Reject
                </button>
            </div>

    </div>
    )


}

function ConfirmEmail({interrupt, onSubmit}) {
    const raw_data = interrupt.current_params
    const[to_email,setTo_email]= useState(raw_data.to_email)
    const[subject,setsubject]= useState(raw_data.subject)
    const[message,setmessage]= useState(raw_data.message)
    const[cc_email,setcc_email]= useState(raw_data.cc_email)
    const[change_to_email,setchange_To_email]= useState(false)
    const[change_subject,setchange_subject]= useState(false)
    const[change_message,setchange_message]= useState(false)
    const[change_cc_email,setchange_cc_email]= useState(false)
    const[feedback,setFeedback] = useState("")
    function handleApprove() {
        const updated_params = {
            to_email,subject,message,cc_email
        };
        onSubmit({ approved: true, updated_params });
    }
    function handleSendSuggestion() {
        const payload = {};
        const updated_params = {
            to_email,subject,message,cc_email
        };
        payload.approved = false;
        payload.updated_params = updated_params
        payload.feedback = feedback
        onSubmit(payload)
    }
    
    // ❌ Reject
    function handleReject() {
        onSubmit({ approved: false, feedback: "User rejected the order." });
    }
    return(
    <div>
        {interrupt.message}
        {!change_to_email &&<span onDoubleClick={() => setchange_To_email(true)} >to_email : {to_email}</span> }
        {change_to_email &&(<div> <input type = "text" value={to_email} onChange={(e) => setTo_email(e.target.value)}/> <button onClick={() => setchange_To_email(false)}>done</button> </div>)}
        
        {!change_subject &&<span onDoubleClick={() => setchange_subject(true)} >subject : {subject}</span> }
        {change_subject &&(<div> <input type = "text" value={subject} onChange={(e) => setsubject(e.target.value)}/> <button onClick={() => setchange_subject(false)}>done</button> </div>)}
        
        {!change_message &&<span onDoubleClick={() => setchange_message(true)} >message : {message}</span> }
        {change_message &&(<div> <input type = "text" value={message} onChange={(e) => setmessage(e.target.value)}/> <button onClick={() => setchange_message(false)}>done</button> </div>)}
        
        {!change_cc_email &&<span onDoubleClick={() => setchange_cc_email(true)} >cc_email : {cc_email}</span> }
        {change_cc_email &&(<div> <input type = "text" value={cc_email} onChange={(e) => setcc_email(e.target.value)}/> <button onClick={() => setchange_cc_email(false)}>done</button> </div>)}
        
        <div style={{ marginBottom: 14 }}>
                <label
                    style={{ display: "block", marginBottom: 5, fontWeight: 600 }}
                >
                    Suggestion / Feedback{" "}
                    <span
                        style={{ fontWeight: 400, color: "#999", fontSize: 12 }}
                    >
                        (optional — send without typing anything is fine too)
                    </span>
                </label>
                <textarea
                    rows={3}
                    value={feedback}
                    onChange={(e) => setFeedback(e.target.value)}
                    placeholder="e.g. Reduce quantity of item X, swap item Y for Z..."
                    style={{width: "100%",boxSizing: "border-box",borderRadius: 5,border: "1px solid #ccc",padding: "8px 10px",fontSize: 13,resize: "vertical",}}
                />
            </div>

            {/* Action buttons */}
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                <button
                    onClick={handleApprove}
                    style={{ ...btnStyle, background: "#28a745", color: "#fff" }}
                >
                    ✅ Approve Email
                </button>

                <button
                    onClick={handleSendSuggestion}
                    style={{ ...btnStyle, background: "#0070f3", color: "#fff" }}
                >
                    💬 Send Suggestion
                </button>

                <button
                    onClick={handleReject}
                    style={{ ...btnStyle, background: "#dc3545", color: "#fff" }}
                >
                    ❌ Reject
                </button>
            </div>

    </div>
    )
}

// ─── Confirm / Edit Order Panel ───────────────────────────────────────────────
function ConfirmOrEditOrderPanel({ interrupt, onSubmit }) {
    const rawItems = interrupt.current_params?.items ?? [];

    // Local editable copy: { product_id, name, quantity, selected }
    const [items, setItems] = useState(() =>
        rawItems.map((item) => ({
            product_id: item.product_id,
            name: item.name,
            quantity: item.quantity,
            selected: false,
        }))
    );
    const [feedback, setFeedback] = useState("");

    // Toggle selection of an item
    function toggleSelect(idx) {
        setItems((prev) =>
            prev.map((item, i) =>
                i === idx ? { ...item, selected: !item.selected } : item
            )
        );
    }

    // Update quantity for a specific item
    function updateQuantity(idx, value) {
        const qty = Math.max(1, parseInt(value) || 1);
        setItems((prev) =>
            prev.map((item, i) =>
                i === idx ? { ...item, quantity: qty } : item
            )
        );
    }

    // ✅ Approve — pass back all items (with any edited quantities)
    function handleApprove() {
        const updated_params = {
            ...interrupt.current_params,
            items: items.map(({ product_id, name, quantity }) => ({
                product_id,
                name,
                quantity,
            })),
        };
        onSubmit({ approved: true, updated_params });
    }

    // 💬 Send Suggestion — selected items (or none) + optional text feedback
    function handleSendSuggestion() {
        const selectedItems = items
            .filter((item) => item.selected)
            .map(({ product_id, name, quantity }) => ({ product_id, name, quantity }));

        const payload = {
            approved: false,
        };

        if (feedback.trim()) {
            payload.feedback = feedback.trim();
        }

        if (selectedItems.length > 0) {
            payload.selected_items = selectedItems;
            // Auto-generate feedback from selection if user typed nothing
            if (!payload.feedback) {
                payload.feedback = `User highlighted items: ${selectedItems
                    .map((i) => i.name)
                    .join(", ")}`;
            }
        }

        // Fallback if nothing was provided at all
        if (!payload.feedback) {
            payload.feedback = "No specific feedback provided.";
        }

        onSubmit(payload);
    }

    // ❌ Reject
    function handleReject() {
        onSubmit({ approved: false, feedback: "User rejected the order." });
    }

    const selectedCount = items.filter((i) => i.selected).length;

    return (
        <div
            style={{
                border: "1px solid #ccc",
                borderRadius: 8,
                padding: 16,
                margin: "12px 0",
                maxWidth: 620,
                background: "#fafafa",
            }}
        >
            <h3 style={{ margin: "0 0 6px" }}>
                📦 Review Order —{" "}
                <em style={{ fontWeight: 400 }}>{interrupt.message}</em>
            </h3>
            <p style={{ fontSize: 13, color: "#666", margin: "0 0 14px" }}>
                Edit quantities if needed, optionally select items to highlight, add a
                suggestion, then click an action below.
            </p>

            {/* Items table */}
            <table
                style={{
                    width: "100%",
                    borderCollapse: "collapse",
                    marginBottom: 14,
                }}
            >
                <thead>
                    <tr style={{ background: "#efefef" }}>
                        <th style={thStyle}>Select</th>
                        <th style={thStyle}>Product ID</th>
                        <th style={thStyle}>Name</th>
                        <th style={thStyle}>Quantity</th>
                    </tr>
                </thead>
                <tbody>
                    {items.map((item, idx) => (
                        <tr
                            key={idx}
                            style={{
                                background: item.selected ? "#dff0ff" : "white",
                                cursor: "pointer",
                                transition: "background 0.15s",
                            }}
                            onClick={() => toggleSelect(idx)}
                        >
                            <td style={tdStyle}>
                                <input
                                    type="checkbox"
                                    checked={item.selected}
                                    onChange={() => toggleSelect(idx)}
                                    onClick={(e) => e.stopPropagation()}
                                />
                            </td>
                            <td style={tdStyle}>{item.product_id}</td>
                            <td style={tdStyle}>{item.name}</td>
                            <td
                                style={tdStyle}
                                onClick={(e) => e.stopPropagation()}
                            >
                                <input
                                    type="number"
                                    min={1}
                                    value={item.quantity}
                                    onChange={(e) =>
                                        updateQuantity(idx, e.target.value)
                                    }
                                    style={{
                                        width: 65,
                                        textAlign: "center",
                                        padding: "3px 4px",
                                        borderRadius: 4,
                                        border: "1px solid #ccc",
                                    }}
                                />
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>

            {/* Feedback / Suggestion textarea */}
            <div style={{ marginBottom: 14 }}>
                <label
                    style={{ display: "block", marginBottom: 5, fontWeight: 600 }}
                >
                    Suggestion / Feedback{" "}
                    <span
                        style={{ fontWeight: 400, color: "#999", fontSize: 12 }}
                    >
                        (optional — send without typing anything is fine too)
                    </span>
                </label>
                <textarea
                    rows={3}
                    value={feedback}
                    onChange={(e) => setFeedback(e.target.value)}
                    placeholder="e.g. Reduce quantity of item X, swap item Y for Z..."
                    style={{
                        width: "100%",
                        boxSizing: "border-box",
                        borderRadius: 5,
                        border: "1px solid #ccc",
                        padding: "8px 10px",
                        fontSize: 13,
                        resize: "vertical",
                    }}
                />
            </div>

            {/* Action buttons */}
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                <button
                    onClick={handleApprove}
                    style={{ ...btnStyle, background: "#28a745", color: "#fff" }}
                >
                    ✅ Approve Order
                </button>

                <button
                    onClick={handleSendSuggestion}
                    style={{ ...btnStyle, background: "#0070f3", color: "#fff" }}
                >
                    💬 Send Suggestion
                    {selectedCount > 0
                        ? ` (${selectedCount} item${selectedCount > 1 ? "s" : ""} selected)`
                        : ""}
                </button>

                <button
                    onClick={handleReject}
                    style={{ ...btnStyle, background: "#dc3545", color: "#fff" }}
                >
                    ❌ Reject
                </button>
            </div>
        </div>
    );
}

// ─── Shared styles ────────────────────────────────────────────────────────────
const thStyle = {
    padding: "8px 10px",
    textAlign: "left",
    borderBottom: "2px solid #ddd",
    fontSize: 13,
    fontWeight: 600,
};
const tdStyle = {
    padding: "7px 10px",
    borderBottom: "1px solid #eee",
    fontSize: 13,
};
const btnStyle = {
    padding: "9px 18px",
    border: "none",
    borderRadius: 5,
    cursor: "pointer",
    fontWeight: 600,
    fontSize: 14,
};


// ─── Confirm / Edit Order Panel ───────────────────────────────────────────────
function ConfirmOrEditProductPanel({ interrupt, onSubmit }) {
    const rawProduct = interrupt.current_params ?? {};

    const [items, setItems] = useState(rawProduct);
    const [feedback, setFeedback] = useState("");
    const[changeName,setChangeName] = useState(false)
    const[description,setChangedescription] = useState(false)
    const[price,setPrice] = useState(false)
    const[category,setcategory] = useState(false)
    const[stock,setStock] = useState(false)
    const[selectedFields,setSelectedFields] = useState([])

    function updateName(e) {
        setItems(prev => ({
            ...prev,
            name: e.target.value
        }));
    }
    function updatedescription(e) {
        setItems(prev => ({
            ...prev,
            description: e.target.value
        }));
    }
    function changePrice(e) {
        setItems(prev => ({
            ...prev,
            price: e.target.value
        }));
    }
    
    function changeCategory(e) {
        setItems(prev => ({
            ...prev,
            category: e.target.value
        }));
    }
    function changeStock(e) {
        setItems(prev => ({
            ...prev,
            stock: e.target.value
        }));
    }

    // ✅ Approve — pass back all items (with any edited quantities)
    function handleApprove() {
        const updated_params = {
            name     : items.name,
            description : items.description,
            price     : items.price,
            category : items.category,
            stock     : items.stock,
            images  : items.images
        };
        onSubmit({ approved: true, updated_params });
    }

    // 💬 Send Suggestion — selected items (or none) + optional text feedback
    function handleSendSuggestion() {
        const payload = {
            approved: false,
        };

        if (feedback.trim()) {
            payload.feedback = feedback.trim();
        }

            payload.selected_fields = selectedFields;
        // Fallback if nothing was provided at all
        if (!payload.feedback) {
            payload.feedback = "No specific feedback provided.";
        }
        payload.updated_params = items
        onSubmit(payload);
    }

    // ❌ Reject
    function handleReject() {
        onSubmit({ approved: false, feedback: "User rejected the product." });
    }

    const selectedCount = selectedFields.length;

    return (
        <div
            style={{
                border: "1px solid #ccc",
                borderRadius: 8,
                padding: 16,
                margin: "12px 0",
                maxWidth: 620,
                background: "#fafafa",
            }}
        >
            <h3 style={{ margin: "0 0 6px" }}>
                📦 Review Product —{" "}
                <em style={{ fontWeight: 400 }}>{interrupt.message}</em>
            </h3>
            <p style={{ fontSize: 13, color: "#666", margin: "0 0 14px" }}>
                Edit fields if needed, optionally select fields to highlight, add a
                suggestion, then click an action below.
            </p>

            {!changeName &&<div> <input
    type="checkbox"
    onChange={(e) => {
        e.target.checked ? setSelectedFields(prev => [...prev, "name"]) : setSelectedFields(prev => prev.filter(field => field !== "name"));}}/><span onDoubleClick={() => setChangeName(true)} >name : {items.name}</span></div> }
            {changeName &&(<div> <input type = "text" value={items.name} onChange={updateName}/> <button onClick={() => setChangeName(false)}>done</button> </div>)}
            
            {!description &&<div> <input
    type="checkbox"
    onChange={(e) => {
        e.target.checked ? setSelectedFields(prev => [...prev, "description"]) : setSelectedFields(prev => prev.filter(field => field !== "description"));}}/> <span onDoubleClick={() => setChangedescription(true)} >description : {items.description}</span></div>}
            {description &&(<div> <input type = "text" value={items.description} onChange={updatedescription}/> <button onClick={() => setChangedescription(false)}>done</button> </div>)}
            
            {!price && <div> <input
    type="checkbox"
    onChange={(e) => {
        e.target.checked ? setSelectedFields(prev => [...prev, "price"]) : setSelectedFields(prev => prev.filter(field => field !== "price"));}}/> <span onDoubleClick={() => setPrice(true)} >price : {items.price}</span></div>}
            {price &&(<div> <input type = "number" value={items.price} onChange={changePrice}/> <button onClick={() => setPrice(false)}>done</button> </div>)}
            
            {!category &&<div>  <input
    type="checkbox"
    onChange={(e) => {
        e.target.checked ? setSelectedFields(prev => [...prev, "category"]) : setSelectedFields(prev => prev.filter(field => field !== "category"));}}/>  <span onDoubleClick={() => setcategory(true)} >category : {items.category}</span></div>}
            {category &&(<div> <input type = "text" value={items.category} onChange={changeCategory}/> <button onClick={() => setcategory(false)}>done</button> </div>)}
            
            {!stock &&<div>  <input
    type="checkbox"
    onChange={(e) => {
        e.target.checked ? setSelectedFields(prev => [...prev, "stock"]) : setSelectedFields(prev => prev.filter(field => field !== "stock"));}}/>  <span onDoubleClick={() => setStock(true)} >stock : {items.stock}</span></div>}
            {stock &&(<div> <input type = "number" value={items.stock} onChange={changeStock}/> <button onClick={() => setStock(false)}>done</button> </div>)}
            
            {/* Feedback / Suggestion textarea */}
            <div style={{ marginBottom: 14 }}>
                <label
                    style={{ display: "block", marginBottom: 5, fontWeight: 600 }}
                >
                    Suggestion / Feedback{" "}
                    <span
                        style={{ fontWeight: 400, color: "#999", fontSize: 12 }}
                    >
                        (optional — send without typing anything is fine too)
                    </span>
                </label>
                <textarea
                    rows={3}
                    value={feedback}
                    onChange={(e) => setFeedback(e.target.value)}
                    placeholder="e.g. Reduce quantity of item X, change description..."
                    style={{
                        width: "100%",
                        boxSizing: "border-box",
                        borderRadius: 5,
                        border: "1px solid #ccc",
                        padding: "8px 10px",
                        fontSize: 13,
                        resize: "vertical",
                    }}
                />
            </div>

            {/* Action buttons */}
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                <button
                    onClick={handleApprove}
                    style={{ ...btnStyle, background: "#28a745", color: "#fff" }}
                >
                    ✅ Approve Product
                </button>

                <button
                    onClick={handleSendSuggestion}
                    style={{ ...btnStyle, background: "#0070f3", color: "#fff" }}
                >
                    💬 Send Suggestion
                    {selectedCount > 0
                        ? ` (${selectedCount} field${selectedCount > 1 ? "s" : ""} selected)`
                        : ""}
                </button>

                <button
                    onClick={handleReject}
                    style={{ ...btnStyle, background: "#dc3545", color: "#fff" }}
                >
                    ❌ Reject
                </button>
            </div>
        </div>
    );
}
