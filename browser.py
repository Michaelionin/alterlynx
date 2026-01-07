import requests
import commonmark
import os
import tempfile
from urllib.parse import urljoin, urlparse
import mimetypes
from PIL import Image
import curses
import time  # Для небольшой задержки при чтении второй цифры
import sys  # Для получения аргументов командной строки


class AlternetBrowser:
    # Константа для URL домашней страницы
    DEFAULT_HOME_URL = "http://ionics.neocities.org/alternet/list.md"
    # Константа для URL списка сайтов
    SITES_LIST_URL = "http://ionics.neocities.org/alternet/list.md"

    def __init__(self):
        # Initialize stdscr as None, it will be set by curses.wrapper
        self.stdscr = None
        self.session = requests.Session()
        self.history = []
        self.current_url = ""
        self.links = []
        self.images = []
        # Set a user-agent to be polite
        self.session.headers.update({'User-Agent': 'Alternet-Browser/1.0'})

        # Initialize display mode: True for simple, False for normal
        self.simple_mode = True  # Упрощенный режим по умолчанию

        # Initialize other attributes but not curses-specific ones yet
        # Colors will be initialized in setup_curses after stdscr is available

    def setup_curses(self):
        """Initialize curses settings and define color pairs."""
        # Now stdscr is guaranteed to be available
        curses.curs_set(0)  # Hide cursor
        self.stdscr.nodelay(0)  # Block on getch() initially
        self.stdscr.timeout(100)  # Timeout for getch in milliseconds for smoother scrolling
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            # Define color pairs: (id, foreground, background)
            # Standard pairs for content
            curses.init_pair(1, curses.COLOR_WHITE, -1)  # Default text
            curses.init_pair(2, curses.COLOR_YELLOW, -1)  # Bold
            curses.init_pair(3, curses.COLOR_CYAN, -1)  # Italic
            curses.init_pair(4, curses.COLOR_BLUE, -1)  # Links
            curses.init_pair(5, curses.COLOR_GREEN, -1)  # Images
            curses.init_pair(6, curses.COLOR_BLACK, curses.COLOR_WHITE)  # Status bar background
            curses.init_pair(7, curses.COLOR_RED, -1)  # Headers

            self.color_default = curses.color_pair(1)
            self.color_bold = curses.color_pair(2) | curses.A_BOLD
            self.color_italic = curses.color_pair(
                3) | curses.A_BOLD  # A_ITALIC not always supported, using BOLD as fallback
            self.color_link = curses.color_pair(4)
            self.color_image = curses.color_pair(5)
            self.color_status = curses.color_pair(6) | curses.A_BOLD
            self.color_header = curses.color_pair(7) | curses.A_BOLD  # Example: Red and Bold
        else:
            # Fallback if colors are not supported
            self.color_default = curses.A_NORMAL
            self.color_bold = curses.A_BOLD
            self.color_italic = curses.A_BOLD  # Fallback to bold
            self.color_link = curses.A_UNDERLINE
            self.color_image = curses.A_DIM
            self.color_status = curses.A_REVERSE
            # Use bold for headers as a fallback
            self.color_header = curses.A_BOLD

    def normalize_url(self, url):
        """Ensures the URL has http:// and appends /main.md if no path is specified."""
        if not url.startswith(('http://', 'https://')):
            url = 'http://' + url

        parsed = urlparse(url)
        if not parsed.path or parsed.path == '/':
            # Check if it already ends with .md to avoid double extension
            if not url.endswith('.md'):
                url += '/main.md'

        return url

    def fetch_markdown(self, url):
        """Fetches the markdown content from the given URL."""
        try:
            response = self.session.get(url)
            response.raise_for_status()

            # Явно указываем, что мы ожидаем UTF-8
            response.encoding = 'utf-8'

            content_type = response.headers.get('Content-Type', '').lower()
            # Check if the response is likely markdown text
            # Allow empty Content-Type or text-based types, especially if URL ends with .md
            is_markdown_url = url.lower().endswith('.md')
            is_text_type = any(t in content_type for t in
                               ['text', 'markdown', 'plain', 'html'])  # 'html' might be served for .md sometimes

            if is_markdown_url or is_text_type:
                return response.text  # Теперь response.text будет декодирован как UTF-8
            else:
                # Return error message to be displayed in the UI
                return f"[ERROR] Expected text/markdown content, got Content-Type: '{content_type}' for URL: {url}"
        except requests.exceptions.RequestException as e:
            return f"[ERROR] Failed to fetch {url}: {e}"

    def render_markdown_to_curses(self, markdown_text, base_url):
        """Renders markdown AST to the curses window."""
        self.links = []  # Reset links list for this page
        self.images = []  # Reset images list for this page
        lines = []  # Store rendered lines
        current_line = ""
        current_attr = self.color_default
        link_counter = 1
        image_counter = 1
        in_code_block = False
        code_block_lang = ""

        # Parse markdown into AST
        ast = commonmark.Parser().parse(markdown_text)
        walker = ast.walker()

        for current, entering in walker:
            node_type = current.t
            literal = current.literal

            if node_type == 'code_block':
                if entering:
                    in_code_block = True
                    code_block_lang = current.info if current.info else "text"
                    current_line += f"\n```{code_block_lang}\n"
                    lines.append((current_line, self.color_default))
                    current_line = ""
                else:
                    current_line += "\n```\n"
                    lines.append((current_line, self.color_default))
                    current_line = ""
                    in_code_block = False
            elif node_type == 'code':
                if entering:
                    current_line += "`"
                else:
                    current_line += "`"
            elif node_type == 'html_inline' or node_type == 'html_block':
                # Skip HTML tags as per requirement
                pass
            elif node_type == 'text':
                if not in_code_block:
                    current_line += literal
                else:
                    current_line += literal
            elif node_type == 'emph':  # Italic
                if entering:
                    # Append current segment with previous attribute before changing
                    if current_line:
                        lines.append((current_line, current_attr))
                        current_line = ""
                    current_attr = self.color_italic
                else:
                    # Append current segment with italic attribute before changing back
                    if current_line:
                        lines.append((current_line, current_attr))
                        current_line = ""
                    current_attr = self.color_default
            elif node_type == 'strong':  # Bold
                if entering:
                    # Append current segment with previous attribute before changing
                    if current_line:
                        lines.append((current_line, current_attr))
                        current_line = ""
                    current_attr = self.color_bold
                else:
                    # Append current segment with bold attribute before changing back
                    if current_line:
                        lines.append((current_line, current_attr))
                        current_line = ""
                    current_attr = self.color_default
            elif node_type == 'link':
                if entering:
                    # Store the destination URL for later use
                    dest_url = urljoin(base_url, current.destination)
                    self.links.append(dest_url)
                    # Append current segment with previous attribute before adding link
                    if current_line:
                        lines.append((current_line, current_attr))
                        current_line = ""

                    if self.simple_mode:
                        # Simple mode: only number and text
                        link_text = f"[{link_counter}]"
                    else:
                        # Normal mode: number and destination
                        link_text = f"[Link {link_counter}: {current.destination}]"

                    lines.append((link_text, self.color_link))
                    current_line = ""  # Reset line after adding link
                    link_counter += 1
                    current_attr = self.color_default  # Reset attribute after link
            elif node_type == 'image':
                if entering:
                    # Store the image source URL for later use
                    img_src = urljoin(base_url, current.destination)
                    self.images.append(img_src)
                    # Append current segment with previous attribute before adding image
                    if current_line:
                        lines.append((current_line, current_attr))
                        current_line = ""

                    if self.simple_mode:
                        # Simple mode: only number and filename
                        filename = os.path.basename(current.destination)
                        image_text = f"[IMG {image_counter}: {filename}]"
                    else:
                        # Normal mode: number and destination
                        image_text = f"[Image {image_counter}: {current.destination}]"

                    lines.append((image_text, self.color_image))
                    current_line = ""  # Reset line after adding image
                    image_counter += 1
                    current_attr = self.color_default  # Reset attribute after image
            elif node_type == 'heading':
                if entering:
                    # Append current segment if any before the heading
                    if current_line:
                        lines.append((current_line, current_attr))
                        current_line = ""
                    # Use the header-specific color/attribute
                    current_attr = self.color_header
                    current_line += "#" * current.level + " "
                else:
                    current_line += "\n"
                    lines.append((current_line, current_attr))
                    current_line = ""
                    current_attr = self.color_default  # Reset attribute after heading
            elif node_type == 'list':
                # Add a newline before the list starts
                if entering and current_line:
                    lines.append((current_line, current_attr))
                    current_line = ""
                elif entering:
                    if not self.simple_mode:  # Add newline in normal mode
                        current_line += "\n"
            elif node_type == 'item':
                # Add a newline and a bullet before the item
                if entering:
                    if current_line:
                        lines.append((current_line, current_attr))
                        current_line = ""
                    if not self.simple_mode:  # Add newline in normal mode
                        current_line += "\n"
                    current_line += " - "
            elif node_type == 'paragraph':
                if not entering:
                    current_line += "\n"
                    if self.simple_mode:  # Add an extra newline for paragraph separation in simple mode
                        current_line += "\n"
                    lines.append((current_line, self.color_default))
                    current_line = ""
            elif node_type == 'block_quote':
                if entering:
                    # In simple mode, just add a space or a symbol to indicate quote
                    if self.simple_mode:
                        current_line += "> "
                    else:
                        current_line += "\n> "
                else:
                    current_line += "\n"
                    lines.append((current_line, self.color_default))
                    current_line = ""
            elif node_type == 'softbreak':
                # In simple mode, treat as space; in normal mode, treat as space (as before)
                if not self.simple_mode:
                    current_line += " "
                else:
                    current_line += " "
            elif node_type == 'linebreak':
                # In simple mode, treat as newline; in normal mode, treat as newline (as before)
                current_line += "\n"
                if not self.simple_mode:
                    lines.append((current_line, self.color_default))
                    current_line = ""
            elif node_type == 'thematic_break':
                # In simple mode, just add a newline; in normal mode, add a line
                if self.simple_mode:
                    current_line += "\n"
                else:
                    current_line += "\n---\n"
                lines.append((current_line, self.color_default))
                current_line = ""

        # Append any remaining text on the current line
        if current_line:
            lines.append((current_line, current_attr))

        # Add a final newline if needed (only if the last line didn't end with \n)
        if current_line and not current_line.endswith('\n'):
            lines.append(("\n", self.color_default))

        return lines

    def display_content(self, lines, scroll_pos):
        """Displays the rendered content lines starting from scroll_pos."""
        max_y, max_x = self.stdscr.getmaxyx()
        status_bar_height = 2
        content_start_y = 1
        content_end_y = max_y - status_bar_height - 1

        self.stdscr.erase()

        # Display URL bar
        self.stdscr.addstr(0, 0, f"URL: {self.current_url[:max_x - 6]}", curses.A_REVERSE)
        self.stdscr.clrtoeol()  # Clear to end of line

        # Display content lines
        line_idx = scroll_pos
        disp_y = content_start_y
        while disp_y <= content_end_y and line_idx < len(lines):
            text, attr = lines[line_idx]
            # Split text by newlines to handle multi-line strings in one element
            text_parts = text.split('\n')
            for i, part in enumerate(text_parts):
                if disp_y > content_end_y:
                    break
                # Add the part of the line
                try:
                    self.stdscr.addstr(disp_y, 0, part.ljust(max_x), attr)
                    self.stdscr.clrtoeol()  # Clear to end of line to avoid artifacts
                except curses.error:
                    # Ignore if trying to addstr outside window bounds
                    pass

                # Move to next line only if it's not the last part of the split
                if i < len(text_parts) - 1:
                    disp_y += 1
            line_idx += 1
            disp_y += 1

        # Display status bar
        mode_text = "SIMPLE" if self.simple_mode else "NORMAL"
        status_text = f"Mode: {mode_text} | Lines: {len(lines)} | Scroll: {scroll_pos + 1}/{len(lines)} | Links: {len(self.links)} Images: {len(self.images)} | Keys: j/k/pgup/pgdn - scroll, g/G - top/bottom, b - back, q - quit, l<n> - link, i<n> - image, m - toggle mode, s - search sites"
        # Truncate status text if necessary
        status_text = status_text[:max_x - 1]
        self.stdscr.addstr(max_y - status_bar_height, 0, status_text, self.color_status)
        self.stdscr.clrtoeol()
        self.stdscr.addstr(max_y - 1, 0, f"Current: {self.current_url[:max_x - 11]}", self.color_status)
        self.stdscr.clrtoeol()

        self.stdscr.refresh()

    def search_sites(self):
        """Displays a search interface for sites listed in SITES_LIST_URL."""
        # Prompt for search query
        self.stdscr.clear()
        self.stdscr.addstr(0, 0, "Alternet Site Search", curses.A_REVERSE)
        self.stdscr.clrtoeol()
        self.stdscr.addstr(2, 0, "Enter search query: ", curses.A_BOLD)
        self.stdscr.refresh()

        # Get search query
        search_query = ""
        y, x = 2, 22
        while True:
            char = self.stdscr.getch()
            if char == 10 or char == 13:  # Enter key
                break
            elif char == ord('q') or char == ord('Q'):  # Quit
                return None
            elif char == curses.KEY_BACKSPACE or char == 127 or char == 8:  # Backspace
                if len(search_query) > 0:
                    search_query = search_query[:-1]
                    # Redraw line to remove character
                    self.stdscr.move(y, x)
                    self.stdscr.clrtoeol()
                    self.stdscr.addstr(y, x, search_query)
            elif 32 <= char <= 126:  # Printable characters
                search_query += chr(char)
                self.stdscr.addstr(y, x + len(search_query) - 1, chr(char))
            self.stdscr.refresh()

        if not search_query:
            # If query is empty, perhaps show all or just return
            msg = "Empty query. Press any key to return."
            self.stdscr.addstr(4, 0, msg[:curses.COLS - 1], curses.color_pair(1) | curses.A_REVERSE)
            self.stdscr.clrtoeol()
            self.stdscr.refresh()
            self.stdscr.getch()  # Wait for keypress
            return None

        # Fetch the list of sites
        markdown_content = self.fetch_markdown(self.SITES_LIST_URL)
        if not markdown_content or markdown_content.startswith("[ERROR]"):
            error_msg = f"Failed to load site list: {markdown_content if markdown_content else 'No content'}"
            self.stdscr.addstr(4, 0, error_msg[:curses.COLS - 1], curses.color_pair(1) | curses.A_REVERSE)
            self.stdscr.clrtoeol()
            self.stdscr.refresh()
            self.stdscr.getch()  # Wait for keypress to acknowledge
            return None

        # Parse markdown to extract links and their text content
        ast = commonmark.Parser().parse(markdown_content)
        walker = ast.walker()

        sites = []  # List of (link_text, destination_url)
        current_link_text = ""  # To accumulate text *inside* the link

        for current, entering in walker:
            node_type = current.t
            literal = current.literal

            if node_type == 'link':
                if entering:
                    # Start collecting text for this link
                    current_link_text = ""
                else:  # exiting the link node
                    # The destination URL is current.destination
                    dest_url = urljoin(self.SITES_LIST_URL, current.destination)
                    # Use the accumulated text inside the link as the link text
                    link_text = current_link_text.strip()
                    if link_text and dest_url:  # Only add if both exist
                        sites.append((link_text, dest_url))
                    # Reset for the next link
                    current_link_text = ""
            elif node_type == 'text' and current_link_text is not None:
                # If we are inside a link (current_link_text is not None),
                # add the text literal to the current link's text
                current_link_text += literal

        # Filter sites based on search query (case-insensitive)
        search_lower = search_query.lower()
        filtered_sites = [(name, url) for name, url in sites if search_lower in name.lower()]

        # Display search results
        self.stdscr.clear()
        self.stdscr.addstr(0, 0, f"Alternet Search: '{search_query}'", curses.A_REVERSE)
        self.stdscr.clrtoeol()

        if not filtered_sites:
            self.stdscr.addstr(2, 0, f"No sites found matching '{search_query}'. Press any key to return.",
                               curses.A_NORMAL)
        else:
            self.stdscr.addstr(2, 0,
                               f"Found {len(filtered_sites)} site(s) matching '{search_query}'. Select one (or 'q' to cancel):",
                               curses.A_NORMAL)
            max_y, max_x = self.stdscr.getmaxyx()
            start_display_y = 4
            for i, (name, url) in enumerate(filtered_sites):
                display_num = i + 1
                display_text = f"{display_num}. {name[:max_x - 5]} -> {url[:max_x - 5 - len(name) - 6]}"
                if len(display_text) > max_x - 1:
                    display_text = display_text[:max_x - 4] + "..."
                self.stdscr.addstr(start_display_y + i, 0, display_text, curses.A_NORMAL)
                if start_display_y + i >= max_y - 3:  # Leave space for prompt and error
                    break

        # Prompt for selection if there are results
        if filtered_sites:
            prompt_y = max(5, start_display_y + len(filtered_sites))
            self.stdscr.addstr(prompt_y, 0, "Enter number: ", curses.A_BOLD)
            self.stdscr.refresh()

            # Get user input for selection
            input_str = ""
            y, x = prompt_y, 14
            while True:
                char = self.stdscr.getch()
                if char == 10 or char == 13:  # Enter key
                    break
                elif char == ord('q') or char == ord('Q'):  # Quit
                    return None
                elif char == curses.KEY_BACKSPACE or char == 127 or char == 8:  # Backspace
                    if len(input_str) > 0:
                        input_str = input_str[:-1]
                        # Redraw line to remove character
                        self.stdscr.move(y, x)
                        self.stdscr.clrtoeol()
                        self.stdscr.addstr(y, x, input_str)
                elif 48 <= char <= 57:  # Digits 0-9
                    input_str += chr(char)
                    self.stdscr.addstr(y, x + len(input_str) - 1, chr(char))
                self.stdscr.refresh()

            # Process the input
            try:
                selection_num = int(input_str)
                if 1 <= selection_num <= len(filtered_sites):
                    selected_url = filtered_sites[selection_num - 1][1]
                    return selected_url
                else:
                    error_msg = f"Invalid selection: {selection_num}. Must be between 1 and {len(filtered_sites)}."
                    self.stdscr.addstr(prompt_y + 2, 0, error_msg[:curses.COLS - 1],
                                       curses.color_pair(1) | curses.A_REVERSE)
                    self.stdscr.clrtoeol()
                    self.stdscr.refresh()
                    self.stdscr.getch()  # Wait for keypress
                    return self.search_sites()  # Recursive call to try again
            except ValueError:
                error_msg = f"Invalid input: '{input_str}'. Please enter a number."
                self.stdscr.addstr(prompt_y + 2, 0, error_msg[:curses.COLS - 1],
                                   curses.color_pair(1) | curses.A_REVERSE)
                self.stdscr.clrtoeol()
                self.stdscr.refresh()
                self.stdscr.getch()  # Wait for keypress
                return self.search_sites()  # Recursive call to try again
        else:
            # No results, just wait for a key press to return
            self.stdscr.refresh()
            self.stdscr.getch()
            return None

    def open_image(self, image_url):
        """Downloads and opens an image using PIL/Pillow."""
        try:
            response = self.session.get(image_url)
            response.raise_for_status()
            image_data = response.content

            # Guess the file extension from the URL or content-type
            parsed_url = urlparse(image_url)
            _, ext = os.path.splitext(parsed_url.path)
            if not ext:
                content_type = response.headers.get('Content-Type', '')
                ext = mimetypes.guess_extension(content_type.split(';')[0]) or '.jpg'  # fallback

            # Create a temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp_file:
                tmp_file.write(image_data)
                temp_filename = tmp_file.name

            # Open the image using PIL, which uses the system's default viewer
            img = Image.open(temp_filename)
            img.show()

            # Optionally, delete the temp file after a delay or prompt
            # os.unlink(temp_filename) # Uncomment if you want to auto-delete

        except Exception as e:
            # Return error message to be displayed potentially in a pop-up or status
            error_msg = f"Could not open image {image_url}: {e}"
            self.stdscr.addstr(curses.LINES - 3, 0, error_msg[:curses.COLS - 1],
                               curses.color_pair(1) | curses.A_REVERSE)
            self.stdscr.clrtoeol()
            self.stdscr.refresh()
            self.stdscr.getch()  # Wait for keypress to acknowledge error

    def run(self):
        """Main loop of the browser using curses."""
        print("Starting Alternet Browser TUI...")  # Initial message before curses takes over
        initial_url = None
        if len(sys.argv) > 1:
            initial_url = sys.argv[1].strip()
        else:
            # Если аргумент не передан, используем домашнюю страницу по умолчанию
            initial_url = self.DEFAULT_HOME_URL
        curses.wrapper(self.main_curses, initial_url)

    def main_curses(self, stdscr, initial_url_arg):
        """Main curses application logic."""
        # Now stdscr is available, assign it
        self.stdscr = stdscr
        # Setup curses settings and colors now that stdscr is ready
        self.setup_curses()

        initial_url = initial_url_arg
        # Проверка на None или пустую строку уже не нужна, так как мы устанавливаем DEFAULT_HOME_URL
        if not initial_url:
            return  # Exit if somehow initial_url is still empty after DEFAULT_HOME_URL fallback

        url = self.normalize_url(initial_url)
        self.history.append(url)
        scroll_pos = 0

        while True:
            markdown_content = self.fetch_markdown(url)
            # Check if fetch_markdown returned an error message instead of content
            if markdown_content.startswith("[ERROR]"):
                # Display error message as content
                lines = self.render_markdown_to_curses(f"# Fetch Error\n\n{markdown_content}", url)
            else:
                lines = self.render_markdown_to_curses(markdown_content, url)

            self.current_url = url
            max_y, max_x = self.stdscr.getmaxyx()
            status_bar_height = 2
            content_height = max_y - status_bar_height - 1  # Height of content area

            # Ensure scroll position is valid
            max_scroll = max(0, len(lines) - content_height)
            if scroll_pos > max_scroll:
                scroll_pos = max_scroll
            if scroll_pos < 0:
                scroll_pos = 0

            self.display_content(lines, scroll_pos)

            # Get user input
            key = self.stdscr.getch()

            # Handle navigation keys
            if key == ord('q'):
                break
            elif key == ord('k') or key == curses.KEY_UP:  # Up
                scroll_pos = max(0, scroll_pos - 1)
            elif key == ord('j') or key == curses.KEY_DOWN:  # Down
                scroll_pos = min(max_scroll, scroll_pos + 1)
            elif key == curses.KEY_PPAGE:  # Page Up
                scroll_pos = max(0, scroll_pos - content_height)
            elif key == curses.KEY_NPAGE:  # Page Down
                scroll_pos = min(max_scroll, scroll_pos + content_height)
            elif key == ord('g') or key == curses.KEY_HOME:  # Go to top
                scroll_pos = 0
            elif key == ord('G') or key == curses.KEY_END:  # Go to bottom
                scroll_pos = max_scroll
            elif key == ord('b'):  # Back
                if len(self.history) > 1:
                    self.history.pop()  # Remove current page
                    url = self.history[-1]  # Go to previous
                    scroll_pos = 0  # Reset scroll on back
                else:
                    # Display message if no history
                    msg = "No previous page in history."
                    self.stdscr.addstr(curses.LINES - 3, 0, msg[:curses.COLS - 1],
                                       curses.color_pair(1) | curses.A_REVERSE)
                    self.stdscr.clrtoeol()
                    self.stdscr.refresh()
                    self.stdscr.getch()  # Wait for keypress to acknowledge
            elif key == ord('m'):  # Toggle mode
                self.simple_mode = not self.simple_mode
                # Redraw after toggling mode
                continue  # Skip the rest of the loop iteration to redraw immediately
            elif key == ord('s'):  # Search sites
                selected_url = self.search_sites()
                if selected_url:
                    # Add current URL to history before navigating to search result
                    if self.current_url != self.history[-1]:
                        self.history.append(self.current_url)
                    url = self.normalize_url(selected_url)
                    scroll_pos = 0  # Reset scroll on search result click
                # Redraw after search (whether a site was selected or not)
                continue  # Skip the rest of the loop iteration to redraw immediately
            elif key in (ord('l'), ord('i')):  # Handle link/image selection
                # Temporarily switch to non-blocking mode to get the number
                self.stdscr.nodelay(1)
                num_char1 = self.stdscr.getch()
                num_char2 = -1  # Initialize as invalid
                # Check if the first char is a digit
                if 48 <= num_char1 <= 57:  # '0' to '9'
                    num_str = chr(num_char1)
                    # Try to get a potential second digit immediately
                    # getch() in nodelay mode returns -1 if no input
                    time.sleep(0.01)  # Small delay to allow input buffer to fill
                    num_char2 = self.stdscr.getch()
                    if 48 <= num_char2 <= 57:  # '0' to '9'
                        num_str += chr(num_char2)
                    else:
                        # If second char is not a digit, put it back if it was valid input
                        if num_char2 != -1:
                            curses.ungetch(num_char2)
                else:
                    # If first char after 'l'/'i' is not a digit, put it back
                    if num_char1 != -1:
                        curses.ungetch(num_char1)
                    num_str = ""  # Indicate no valid number found

                # Switch back to blocking mode
                self.stdscr.nodelay(0)
                self.stdscr.timeout(100)  # Restore timeout

                try:
                    if num_str:
                        num = int(num_str)
                        if key == ord('l'):  # Link
                            if 1 <= num <= len(self.links):
                                new_url = self.links[num - 1]
                                if self.current_url != self.history[-1]:
                                    self.history.append(self.current_url)
                                url = self.normalize_url(new_url)
                                scroll_pos = 0  # Reset scroll on link click
                            else:
                                msg = f"Invalid link number: {num}. Valid range: 1-{len(self.links)}."
                                self.stdscr.addstr(curses.LINES - 3, 0, msg[:curses.COLS - 1],
                                                   curses.color_pair(1) | curses.A_REVERSE)
                                self.stdscr.clrtoeol()
                                self.stdscr.refresh()
                                self.stdscr.getch()
                        elif key == ord('i'):  # Image
                            if 1 <= num <= len(self.images):
                                img_url = self.images[num - 1]
                                self.open_image(img_url)
                            else:
                                msg = f"Invalid image number: {num}. Valid range: 1-{len(self.images)}."
                                self.stdscr.addstr(curses.LINES - 3, 0, msg[:curses.COLS - 1],
                                                   curses.color_pair(1) | curses.A_REVERSE)
                                self.stdscr.clrtoeol()
                                self.stdscr.refresh()
                                self.stdscr.getch()
                    else:
                        # No valid number was entered after 'l' or 'i'
                        msg = f"Command '{chr(key)}' requires a number. Press '{chr(key)}' followed by link/image number."
                        self.stdscr.addstr(curses.LINES - 3, 0, msg[:curses.COLS - 1],
                                           curses.color_pair(1) | curses.A_REVERSE)
                        self.stdscr.clrtoeol()
                        self.stdscr.refresh()
                        self.stdscr.getch()
                except ValueError:
                    # Should not happen if num_str is checked correctly, but just in case
                    msg = f"Invalid number format: {num_str}"
                    self.stdscr.addstr(curses.LINES - 3, 0, msg[:curses.COLS - 1],
                                       curses.color_pair(1) | curses.A_REVERSE)
                    self.stdscr.clrtoeol()
                    self.stdscr.refresh()
                    self.stdscr.getch()
            # Add a default case to handle unrecognized keys if needed
            # elif key != -1: # -1 is returned by getch in nodelay mode if no key is pressed
            #     # Optionally handle other keys or ignore them
            #     pass

    def prompt_url(self):
        """Prompt for URL using a simple curses input."""
        self.stdscr.clear()
        self.stdscr.addstr(0, 0, "Alternet Browser - Enter URL (e.g., http://example.com/alternet):")
        self.stdscr.addstr(1, 0, "> ")
        self.stdscr.refresh()

        # Simple input buffer
        input_str = ""
        y, x = 1, 2
        while True:
            char = self.stdscr.getch()
            if char == 10 or char == 13:  # Enter key
                break
            elif char == 27:  # ESC key
                input_str = ""
                break
            elif char == curses.KEY_BACKSPACE or char == 127 or char == 8:  # Backspace
                if len(input_str) > 0:
                    input_str = input_str[:-1]
                    # Redraw line to remove character
                    self.stdscr.move(y, x)
                    self.stdscr.clrtoeol()
                    self.stdscr.addstr(y, x, input_str)
            elif 32 <= char <= 126:  # Printable characters
                input_str += chr(char)
                self.stdscr.addstr(y, x + len(input_str) - 1, chr(char))
            self.stdscr.refresh()

        self.stdscr.clear()
        self.stdscr.refresh()
        return input_str.strip()


if __name__ == "__main__":
    browser = AlternetBrowser()  # Pass None initially, stdscr is set later by curses.wrapper
    browser.run()  # This will call curses.wrapper and initialize stdscr properly