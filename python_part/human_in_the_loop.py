import json
from langgraph.types import interrupt
from langchain_core.messages import HumanMessage

    # Import your LLM so we can use it to rewrite content
from llm_config import llm 
async def hitl_login_wrapper(original_tool, state, prv, depended, params=None):
    """
    Auto-logs in if credentials exist in state; otherwise informs that credentials are absent.
    """
    if params is None:
        params = {}

    # Check for social media or ecommerce credentials in state
    email = state.get("social_media_user_name") or state.get("ecommerce_user_name")
    password = state.get("social_media_password") or state.get("ecommerce_password")

    if email and password:
        params["email"] = email
        params["password"] = password
        print(f"[INFO] Auto-logging in with stored credentials for {email}")
        return await original_tool(state, prv, depended, str(params))

    # If no credentials exist, do not block the graph with an interrupt
    return "Notice: No login credentials provided in database. Actions requiring authentication will generate content for manual execution."
async def hitl_confirm_create_product(original_tool, tool_name, state, prv, depended, params=None):
    """
    Interrupts the graph to ask the user to confirm or edit a product
    before it is created.

    Product fields: name, description, price, category, stock, images (List[str])

    The frontend can respond with:
      - { approved: True, updated_params: { name, description, price, ... } }
          → execute immediately with the (possibly edited) params
      - { approved: False, feedback: "...", selected_fields: ["price", "description"] }
          → ask the LLM to revise only those fields and loop again
    """
    if params is None:
        params = {}

    current_params = params.copy()

    while True:
        user_response = interrupt({
            "action": "confirm_or_edit_create_product",
            "tool_name": tool_name,
            "current_params": current_params,
            "message": tool_name,
        })

        updated_params = user_response.get("updated_params", current_params)
        # ── Approved ──────────────────────────────────────────────────────────
        if user_response.get("approved"):
            return await original_tool(state, prv, depended, str(updated_params))
        current_params = updated_params
        # ── Not approved: LLM rewrite based on feedback ───────────────────────
        feedback = user_response.get("feedback", "Make it better.")
        selected_fields = user_response.get("selected_fields")  # optional list from UI

        selected_context = ""
        if selected_fields:
            selected_context = (
                f"\nThe user wants you to specifically fix these fields: {', '.join(selected_fields)}"
            )

        prompt = f"""
You are helping revise a product listing based on user feedback.

User feedback: "{feedback}"{selected_context}

Current product details:
  name        : {current_params.get('name', '')}
  description : {current_params.get('description', '')}
  price       : {current_params.get('price', 0)}
  category    : {current_params.get('category', '')}
  stock       : {current_params.get('stock', 0)}
  images      : {json.dumps(current_params.get('images', []))}

Return ONLY valid JSON with exactly these keys:
  "name"        - product name (string)
  "description" - product description (string)
  "price"       - product price (float)
  "category"    - product category (string)
  "stock"       - stock quantity (integer)
  "images"      - list of image URL strings
"""

        res = await llm.ainvoke([HumanMessage(content=prompt)])

        try:
            clean_json = res.content.replace("```json", "").replace("```", "").strip()
            new_data = json.loads(clean_json)
            for field in ("name", "description", "price", "category", "stock", "images"):
                if field in new_data:
                    current_params[field] = new_data[field]
        except Exception as e:
            print(f"Failed to parse LLM rewrite: {e}")


async def hitl_confirm_create_order(original_tool, tool_name, state, prv, depended, params=None):
    """
    Interrupts the graph to ask the user to confirm or edit the parameters
    before creating an order.

    The frontend can respond with:
      - { approved: True, updated_params: { items, shipping_address, ... } }
          → execute immediately with the updated params
      - { approved: False, feedback: "...", selected_items: [...] }
          → ask the LLM to revise the order and loop again
    """
    if params is None:
        params = {}

    current_params = params.copy()

    while True:
        user_response = interrupt({
            "action": "confirm_or_edit_create_order",
            "tool_name": tool_name,
            "current_params": current_params,
            "message": tool_name,
        })

        # ── Approved: run the tool with (possibly edited) params ──────────────
        if user_response.get("approved"):
            updated_params = user_response.get("updated_params", current_params)
            return await original_tool(state, prv, depended, str(updated_params))

        # ── Not approved: collect feedback + any highlighted items ────────────
        feedback = user_response.get("feedback", "Make it better.")
        selected_items = user_response.get("selected_items")  # optional list from UI

        # Build extra context for the LLM when the user highlighted specific items
        selected_context = ""
        if selected_items:
            selected_context = (
                f"\nThe user specifically highlighted these items: {json.dumps(selected_items)}"
            )

        prompt = f"""
            You are helping revise a customer order based on user feedback.

            User feedback: "{feedback}"{selected_context}

            Current items (JSON):
            {json.dumps(current_params.get('items', []), indent=2)}

            Current shipping_address: {current_params.get('shipping_address', '')}

            Return ONLY valid JSON with exactly two keys:
            "items"            - updated list of items, each with product_id, name, quantity
            "shipping_address" - updated shipping address string
        """

        res = await llm.ainvoke([HumanMessage(content=prompt)])

        try:
            clean_json = res.content.replace("```json", "").replace("```", "").strip()
            new_data = json.loads(clean_json)
            current_params["items"] = new_data.get("items", current_params.get("items"))
            current_params["shipping_address"] = new_data.get(
                "shipping_address", current_params.get("shipping_address")
            )
        except Exception as e:
            print(f"Failed to parse LLM rewrite: {e}")


async def hitl_confirm_create_order(original_tool, tool_name, state, prv, depended, params=None):
    if params is None:
        params = {}

    current_params = params.copy()
    has_credentials = bool(
        state.get("ecommerce_user_name") and state.get("ecommerce_password")
    )

    while True:
        user_response = interrupt({
            "action": "confirm_or_edit_create_order",
            "tool_name": tool_name,
            "current_params": current_params,
            "message": tool_name if has_credentials else "⚠️ Ecommerce credentials missing. Review order details below:",
            "has_credentials": has_credentials
        })

        if user_response.get("approved"):
            updated_params = user_response.get("updated_params", current_params)

            # IF CREDENTIALS NOT PRESENT: Return details for manual completion
            if not has_credentials:
                items_str = json.dumps(updated_params.get('items', []), indent=2)
                address = updated_params.get('shipping_address', 'Not specified')
                return (
                    f"⚠️ Ecommerce credentials are not configured.\n\n"
                    f"🛒 Order Details Generated:\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📦 Items:\n{items_str}\n\n"
                    f"📍 Shipping Address: {address}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"👉 Please complete the purchase manually on the store website using these details."
                )

            # IF CREDENTIALS ARE PRESENT: Call the ecommerce API
            return await original_tool(state, prv, depended, str(updated_params))

        # Handle revision feedback
        feedback = user_response.get("feedback", "Make it better.")
        prompt = f"""
            Rewrite the email based on feedback: "{feedback}"
            Current Subject: {current_params.get('subject', '')}
            Current Message: {current_params.get('message', '')}
            Return ONLY valid JSON with keys: 'subject' and 'message'.
        """
        res = await llm.ainvoke([HumanMessage(content=prompt)])
        try:
            clean_json = res.content.replace("```json", "").replace("```", "").strip()
            new_data = json.loads(clean_json)
            current_params["subject"] = new_data.get("subject", current_params.get("subject"))
            current_params["message"] = new_data.get("message", current_params.get("message"))
        except Exception as e:
            print(f"Failed to parse rewrite: {e}")
async def hitl_create_post_wrapper(original_tool, state, prv, depended, params=None):
    if params is None:
        params = {}
        
    current_params = params.copy()
    
    # Check if social media credentials exist
    has_credentials = bool(
        state.get("social_media_user_name") and state.get("social_media_password")
    )
    
    while True:
        # 1. Pause graph for user review
        prompt_message = "Preview the post." if has_credentials else "⚠️ No social media credentials found. Review generated content below:"
        user_response = interrupt({
            "action": "preview_post",
            "current_params": current_params,
            "message": prompt_message,
            "has_credentials": has_credentials
        })
        
        # 2. User approved the post
        updated_params = user_response.get("updated_params", current_params)
        if user_response.get("approved"):
            if "published" in user_response:
                updated_params["published"] = user_response["published"]

            # IF CREDENTIALS NOT PRESENT: Give generated content to user to do manually
            if not has_credentials:
                title = updated_params.get('title', '')
                content = updated_params.get('content', '')
                tags = ", ".join(updated_params.get('tags') or [])
                category = updated_params.get('category', '')

                return (
                    f"⚠️ Social media credentials are not configured.\n\n"
                    f"✅ Content has been successfully generated for you:\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📌 Title: {title}\n"
                    f"📂 Category: {category}\n"
                    f"🏷️ Tags: {tags}\n\n"
                    f"📝 Content:\n{content}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"👉 Please copy the generated content above and publish it manually on your account."
                )

            # IF CREDENTIALS ARE PRESENT: Execute API call
            return await original_tool(state, prv, depended, str(updated_params))
            
        # 3. User requested revisions
        feedback = user_response.get("feedback", "Make it better.")
        prompt = f"""
        Rewrite this post based on the following user feedback: "{feedback}"
        Original context: {prv}
        Current Title: {current_params.get('title', '')}
        Current Content: {current_params.get('content', '')}
        tags: {", ".join(current_params.get('tags') or [])}
        category : {current_params.get('category', '')}
        Return ONLY valid JSON with keys: 'title', 'content', 'category' and 'tags' (array of strings).
        """
        res = await llm.ainvoke([HumanMessage(content=prompt)])
        try:
            clean_json = res.content.replace("```json", "").replace("```", "").strip()
            new_data = json.loads(clean_json)
            current_params["title"] = new_data.get("title", current_params.get("title"))
            current_params["content"] = new_data.get("content", current_params.get("content"))
            current_params["category"] = new_data.get("category", current_params.get("category"))
            current_params["tags"] = new_data.get("tags", current_params.get("tags"))
        except Exception as e:
            print(f"Failed to parse rewrite: {e}")