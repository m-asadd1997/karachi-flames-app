import streamlit as st
import pandas as pd
import psycopg2
import time

# --- DATABASE SETUP ---
DB_URL = st.secrets["DATABASE_URL"]

@st.cache_resource
def get_db_connection():
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True 
    
    with conn.cursor() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS tournaments
                     (id SERIAL PRIMARY KEY, name TEXT UNIQUE, fee REAL, total_matches INTEGER, deadline INTEGER, current_match INTEGER DEFAULT 1)''')
        c.execute('''CREATE TABLE IF NOT EXISTS players
                     (id SERIAL PRIMARY KEY, name TEXT, tournament_id INTEGER)''')
        c.execute('''CREATE TABLE IF NOT EXISTS payments
                     (id SERIAL PRIMARY KEY, player_id INTEGER, tournament_id INTEGER, amount REAL, match_number INTEGER, date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    return conn

conn = get_db_connection()

# --- HELPER FUNCTIONS ---
def get_tournaments():
    return pd.read_sql_query("SELECT * FROM tournaments ORDER BY id DESC", conn)

def get_players(tournament_id):
    return pd.read_sql_query("SELECT * FROM players WHERE tournament_id = %s ORDER BY name ASC", conn, params=(tournament_id,))

def get_payments(tournament_id):
    query = """
        SELECT pay.id, pay.player_id, p.name as player_name, pay.amount, pay.match_number, pay.date 
        FROM payments pay 
        JOIN players p ON pay.player_id = p.id 
        WHERE pay.tournament_id = %s 
        ORDER BY pay.date DESC
    """
    return pd.read_sql_query(query, conn, params=(tournament_id,))

def get_match_payments(tournament_id, match_number):
    query = "SELECT id, player_id, amount FROM payments WHERE tournament_id = %s AND match_number = %s"
    return pd.read_sql_query(query, conn, params=(tournament_id, match_number))

# --- UI SETUP ---
st.set_page_config(page_title="Team Finance Manager", page_icon="🏏", layout="wide")
st.title("🏏 Team Finance Manager")

# --- SIDEBAR: TOURNAMENTS ---
tournaments_df = get_tournaments()
t_names = tournaments_df['name'].tolist() if not tournaments_df.empty else []

with st.sidebar:
    st.header("🏆 Add Tournament")
    with st.form("new_tournament", clear_on_submit=True):
        t_name = st.text_input("Tournament Name")
        t_fee = st.number_input("Total Entry Fee", min_value=0, step=1000)
        t_matches = st.number_input("Total Matches", min_value=1, step=1)
        t_deadline = st.number_input("Deadline Match No.", min_value=1, step=1)
        
        if st.form_submit_button("Create Tournament", use_container_width=True):
            if t_name.strip() and t_fee > 0:
                try:
                    with conn.cursor() as c:
                        c.execute("INSERT INTO tournaments (name, fee, total_matches, deadline, current_match) VALUES (%s, %s, %s, %s, 1)", 
                                  (t_name.strip(), t_fee, t_matches, t_deadline))
                    st.toast(f"'{t_name}' created!", icon="✅")
                    time.sleep(1)
                    st.rerun()
                except psycopg2.IntegrityError:
                    st.error("Tournament name already exists.")

# --- MAIN APP ---
if tournaments_df.empty:
    st.info("👈 Please create your first tournament in the sidebar menu to get started.")
else:
    active_t_name = st.selectbox("Active Tournament Dashboard", t_names)
    active_t = tournaments_df[tournaments_df['name'] == active_t_name].iloc[0]
    t_id = int(active_t['id'])
    cur_match = int(active_t.get('current_match', 1))

    with st.expander("⚙️ Tournament Settings"):
        new_t_name = st.text_input("Name", value=active_t['name'])
        new_t_fee = st.number_input("Fee", value=int(active_t['fee']), step=1000)
        new_t_match = st.number_input("Current Active Match", value=cur_match, min_value=1, step=1)
        
        c_save, c_del = st.columns(2)
        if c_save.button("Save Updates", use_container_width=True):
            with conn.cursor() as c:
                c.execute("UPDATE tournaments SET name=%s, fee=%s, current_match=%s WHERE id=%s", (new_t_name, new_t_fee, new_t_match, t_id))
            st.toast("Settings updated!", icon="🔄")
            time.sleep(1)
            st.rerun()
        if c_del.button("🚨 Wipe Tournament", type="primary", use_container_width=True):
            with conn.cursor() as c:
                c.execute("DELETE FROM payments WHERE tournament_id=%s", (t_id,))
                c.execute("DELETE FROM players WHERE tournament_id=%s", (t_id,))
                c.execute("DELETE FROM tournaments WHERE id=%s", (t_id,))
            st.rerun()

    # --- NEW APP STRUCTURE ---
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Dashboard", "🏏 Match Center", "💸 History", "👥 Roster"])
    
    # --- TAB 1: DASHBOARD ---
    with tab1:
        payments_df = get_payments(t_id)
        total_collected = payments_df['amount'].sum() if not payments_df.empty else 0.0
        remaining = active_t['fee'] - total_collected
        
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Total Fee", f"{active_t['fee']:,.0f}")
        col_b.metric("Collected", f"{total_collected:,.0f}")
        col_c.metric("Remaining", f"{remaining:,.0f}")
        
        st.progress(float(min(total_collected / active_t['fee'], 1.0)) if active_t['fee'] > 0 else 0.0)
        st.divider()
        
        target_per_match = active_t['fee'] / active_t['deadline'] if active_t['deadline'] > 0 else 0
        match_pay_df = get_match_payments(t_id, cur_match)
        match_collected = match_pay_df['amount'].sum() if not match_pay_df.empty else 0.0
            
        st.write(f"### 🎯 Focus: Match {cur_match} Progress")
        st.metric("Collected for Current Match", f"{match_collected:,.0f} / {target_per_match:,.0f} PKR")
        st.progress(float(min(match_collected / target_per_match, 1.0)) if target_per_match > 0 else 0.0)
        
        if st.button(f"✅ Close Match {cur_match} & Start Match {cur_match + 1}", use_container_width=True, type="primary"):
            with conn.cursor() as c:
                c.execute("UPDATE tournaments SET current_match = current_match + 1 WHERE id=%s", (t_id,))
            st.rerun()

    # --- TAB 2: MATCH CENTER (NEW UX) ---
    with tab2:
        st.write("### 🏏 Match Payments Workspace")
        st.caption("Select your squad, and the app will auto-calculate the per-head fee. Check the box to instantly mark them as paid.")
        
        players_df = get_players(t_id)
        if players_df.empty:
            st.warning("Please add players in the 'Roster' tab first.")
        else:
            # 1. Match Selector
            selected_match = st.number_input("Select Match Context", min_value=1, max_value=int(active_t['total_matches']), value=cur_match, step=1)
            target_per_match = active_t['fee'] / active_t['deadline'] if active_t['deadline'] > 0 else 0
            
            # 2. Squad Selection
            all_player_ids = players_df['id'].tolist()
            player_dict = dict(zip(players_df.id, players_df.name))
            
            squad_ids = st.multiselect(
                "Select Playing Squad:", 
                options=all_player_ids, 
                default=[], # Starts empty now!
                format_func=lambda x: player_dict[x]
            )
            
            if squad_ids:
                # 3. Auto-Calculate Per Head
                per_head_calc = target_per_match / len(squad_ids) if len(squad_ids) > 0 else 0
                st.info(f"💡 Target: {target_per_match:,.2f} PKR | Squad Size: {len(squad_ids)} | Per-Head Fee: **{per_head_calc:,.2f} PKR**")
                
                # Fetch existing payments to pre-check boxes
                existing_match_pays = get_match_payments(t_id, selected_match)
                
                # Build the checklist DataFrame
                ui_data = []
                for pid in squad_ids:
                    p_name = player_dict[pid]
                    existing_record = existing_match_pays[existing_match_pays['player_id'] == pid]
                    
                    if not existing_record.empty:
                        paid_amt = float(existing_record.iloc[0]['amount'])
                        is_paid = True
                        pay_id = int(existing_record.iloc[0]['id'])
                    else:
                        # Exact calculation rounded to 2 decimal places instead of nearest 100
                        paid_amt = round(per_head_calc, 2)
                        is_paid = False
                        pay_id = -1
                        
                    ui_data.append({
                        "pay_id": pay_id,
                        "player_id": pid,
                        "Player": p_name,
                        "Amount (PKR)": paid_amt,
                        "Paid?": is_paid
                    })
                    
                ui_df = pd.DataFrame(ui_data)
                
                # 4. Interactive Checklist
                st.write("**Mark Payments as Done:**")
                edited_ui_df = st.data_editor(
                    ui_df,
                    column_config={
                        "pay_id": None, 
                        "player_id": None,
                        "Player": st.column_config.TextColumn(disabled=True),
                        "Paid?": st.column_config.CheckboxColumn(required=True)
                    },
                    hide_index=True,
                    use_container_width=True,
                    key=f"match_center_{selected_match}"
                )
                
                # 5. Save Logic
                if st.button("💾 Save Match Payments", type="primary", use_container_width=True):
                    with st.spinner("Processing batch updates..."):
                        with conn.cursor() as c:
                            for idx, row in edited_ui_df.iterrows():
                                original_state = ui_df.iloc[idx]['Paid?']
                                new_state = row['Paid?']
                                
                                # Scenario A: Was unchecked, now checked -> INSERT
                                if not original_state and new_state:
                                    c.execute("INSERT INTO payments (player_id, tournament_id, amount, match_number) VALUES (%s, %s, %s, %s)", 
                                              (row['player_id'], t_id, row['Amount (PKR)'], selected_match))
                                # Scenario B: Was checked, now unchecked -> DELETE
                                elif original_state and not new_state:
                                    c.execute("DELETE FROM payments WHERE id=%s", (row['pay_id'],))
                                # Scenario C: Kept checked, but changed amount -> UPDATE
                                elif original_state and new_state:
                                    original_amt = ui_df.iloc[idx]['Amount (PKR)']
                                    if original_amt != row['Amount (PKR)']:
                                        c.execute("UPDATE payments SET amount=%s WHERE id=%s", (row['Amount (PKR)'], row['pay_id']))
                                        
                    st.toast("Payments synced successfully!", icon="✅")
                    time.sleep(1)
                    st.rerun()

    # --- TAB 3: PAYMENT HISTORY & EDITS ---
    with tab3:
        st.write("### 💸 Payment History")
        payments_df = get_payments(t_id)
        
        if not payments_df.empty:
            # 1. Standardized Filter Flow
            filter_col, search_col = st.columns([1, 1])
            with filter_col:
                view_filter = st.selectbox(
                    "Filter by Match:", 
                    options=["Current Match (Match " + str(cur_match) + ")", "All Matches"] + [f"Match {i}" for i in range(1, int(active_t['total_matches'])+1)]
                )
            
            # Apply Filter
            if view_filter.startswith("Current"):
                filtered_df = payments_df[payments_df['match_number'] == cur_match]
            elif view_filter == "All Matches":
                filtered_df = payments_df
            else:
                match_num_filter = int(view_filter.split(" ")[1])
                filtered_df = payments_df[payments_df['match_number'] == match_num_filter]
                
            # 2. Display filtered data
            if not filtered_df.empty:
                disp_pay = filtered_df[['id', 'player_name', 'amount', 'match_number', 'date']].copy()
                disp_pay.columns = ["id", "Player", "Amount", "Match", "Date"]
                
                st.caption(f"Showing {len(filtered_df)} records. Double-click to edit. Select row & press Delete to remove.")
                st.data_editor(
                    disp_pay,
                    column_config={"id": None, "Player": st.column_config.TextColumn(disabled=True), "Date": st.column_config.DatetimeColumn(disabled=True, format="MMM DD")},
                    num_rows="dynamic",
                    key="history_editor",
                    use_container_width=True
                )
                
                # Excel Export
                csv = disp_pay.drop(columns=['id']).to_csv(index=False).encode('utf-8')
                st.download_button("📥 Export Current View (CSV)", data=csv, file_name=f"payments_{view_filter.replace(' ', '_').lower()}.csv", mime='text/csv')
                
                # Handle Edits/Deletes
                changes = st.session_state.get("history_editor", {"edited_rows": {}, "deleted_rows": []})
                if len(changes["deleted_rows"]) > 0 or len(changes["edited_rows"]) > 0:
                    if st.button("💾 Confirm Changes to History", type="primary", use_container_width=True):
                        with conn.cursor() as c:
                            for row_idx in changes["deleted_rows"]:
                                c.execute("DELETE FROM payments WHERE id=%s", (int(disp_pay.iloc[row_idx]["id"]),))
                            for row_idx, edit in changes["edited_rows"].items():
                                pay_id = int(disp_pay.iloc[row_idx]["id"])
                                if "Amount" in edit: c.execute("UPDATE payments SET amount=%s WHERE id=%s", (edit["Amount"], pay_id))
                                if "Match" in edit: c.execute("UPDATE payments SET match_number=%s WHERE id=%s", (edit["Match"], pay_id))
                        st.rerun()
            else:
                st.info("No records found for this filter.")
        else:
            st.info("No payments recorded yet.")

    # --- TAB 4: MANAGE ROSTER ---
    with tab4:
        st.write("### ➕ Add Player")
        with st.form("add_player", clear_on_submit=True):
            p_name = st.text_input("Player Name", placeholder="Enter player name...")
            if st.form_submit_button("Add to Roster", use_container_width=True, type="primary"):
                if p_name.strip():
                    with conn.cursor() as c: c.execute("INSERT INTO players (name, tournament_id) VALUES (%s, %s)", (p_name.strip(), t_id))
                    st.rerun()

        st.divider()
        st.write("### ✏️ Edit Roster")
        players_df = get_players(t_id)
        if not players_df.empty:
            disp_players = players_df[['id', 'name']].copy()
            disp_players.columns = ["id", "Player Name"]
            st.data_editor(disp_players, column_config={"id": None}, num_rows="dynamic", key="roster_editor", use_container_width=True)
            
            changes = st.session_state.get("roster_editor", {"edited_rows": {}, "deleted_rows": []})
            if len(changes["deleted_rows"]) > 0 or len(changes["edited_rows"]) > 0:
                if st.button("💾 Save Roster Updates", type="primary", use_container_width=True):
                    with conn.cursor() as c:
                        for row_idx in changes["deleted_rows"]:
                            p_id = int(disp_players.iloc[row_idx]["id"])
                            c.execute("DELETE FROM payments WHERE player_id=%s", (p_id,))
                            c.execute("DELETE FROM players WHERE id=%s", (p_id,))
                        for row_idx, edit in changes["edited_rows"].items():
                            if "Player Name" in edit:
                                c.execute("UPDATE players SET name=%s WHERE id=%s", (edit["Player Name"], int(disp_players.iloc[row_idx]["id"])))
                    st.rerun()
        else:
            st.info("No players added yet.")
