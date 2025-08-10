import logging
from typing import List, Optional, Dict
from playwright.sync_api import sync_playwright, Page
from dataclasses import dataclass, asdict
import pandas as pd
import argparse
import platform
import time
import os
from datetime import datetime
import json


@dataclass
class Place:
    name: str = ""
    address: str = ""
    website: str = ""
    phone_number: str = ""
    reviews_count: Optional[int] = None
    reviews_average: Optional[float] = None
    store_shopping: str = "No"
    in_store_pickup: str = "No"
    store_delivery: str = "No"
    place_type: str = ""
    opens_at: str = ""
    introduction: str = ""
    search_keyword: str = ""  # Added to track which keyword found this place
    category: str = ""  # Added to track category


def setup_logging(log_file: str = None):
    if log_file:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler()
            ],
            force=True
        )
    else:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            force=True
        )

    # Set console encoding for Windows
    import sys
    if sys.platform.startswith('win'):
        try:
            import codecs
            sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer)
            sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer)
        except:
            pass


def get_category_from_keyword(keyword: str) -> str:
    """Extract category from keyword"""
    keyword_lower = keyword.lower()
    if any(food in keyword_lower for food in ['bakery', 'hotel', 'restaurant', 'tea shop', 'snacks shop']):
        return 'Food_Businesses'
    elif any(event in keyword_lower for event in ['catering', 'event management']):
        return 'Event_Catering'
    elif any(wholesale in keyword_lower for wholesale in ['wholesale', 'frozen food']):
        return 'Wholesale_Frozen'
    elif any(specialty in keyword_lower for specialty in ['biryani', 'fast food']):
        return 'Specialty_Food'
    elif any(large in keyword_lower for large in ['canteen', 'mess']):
        return 'Large_Scale_Buyers'
    else:
        return 'Other'


def extract_text(page: Page, xpath: str) -> str:
    try:
        if page.locator(xpath).count() > 0:
            return page.locator(xpath).inner_text()
    except Exception as e:
        logging.warning(f"Failed to extract text for xpath {xpath}: {e}")
    return ""


def extract_place(page: Page, search_keyword: str = "", category: str = "") -> Place:
    # XPaths with multiple fallbacks
    name_xpaths = [
        '//div[@class="TIHn2 "]//h1[@class="DUwDvf lfPIob"]',
        '//h1[@class="DUwDvf lfPIob"]',
        '//h1[contains(@class, "DUwDvf")]'
    ]

    address_xpaths = [
        '//button[@data-item-id="address"]//div[contains(@class, "fontBodyMedium")]',
        '//button[contains(@data-item-id, "address")]//div[contains(@class, "fontBodyMedium")]',
        '//div[contains(@class, "Io6YTe")]'
    ]

    website_xpaths = [
        '//a[@data-item-id="authority"]//div[contains(@class, "fontBodyMedium")]',
        '//a[contains(@data-item-id, "authority")]//div[contains(@class, "fontBodyMedium")]',
        '//a[contains(@href, "http")]//div[contains(@class, "fontBodyMedium")]'
    ]

    phone_xpaths = [
        '//button[contains(@data-item-id, "phone:tel:")]//div[contains(@class, "fontBodyMedium")]',
        '//button[contains(@aria-label, "phone") or contains(@aria-label, "Phone")]//div[contains(@class, "fontBodyMedium")]',
        '//div[contains(text(), "+91") or contains(text(), "04")]'
    ]

    reviews_count_xpaths = [
        '//div[@class="TIHn2 "]//div[@class="fontBodyMedium dmRWX"]//div//span//span//span[@aria-label]',
        '//span[contains(@aria-label, "reviews") or contains(@aria-label, "review")]',
        '//span[contains(text(), "review")]'
    ]

    reviews_avg_xpaths = [
        '//div[@class="TIHn2 "]//div[@class="fontBodyMedium dmRWX"]//div//span[@aria-hidden]',
        '//span[@aria-hidden="true" and contains(text(), ".")]',
        '//div[contains(@class, "fontDisplayLarge")]//span'
    ]

    def extract_text_multiple(xpaths: List[str]) -> str:
        """Try multiple XPaths until one works"""
        for xpath in xpaths:
            try:
                if page.locator(xpath).count() > 0:
                    text = page.locator(xpath).first.inner_text().strip()
                    if text:
                        return text
            except Exception as e:
                logging.debug(f"XPath {xpath} failed: {e}")
                continue
        return ""

    place = Place()
    place.name = extract_text_multiple(name_xpaths)
    place.address = extract_text_multiple(address_xpaths)
    place.website = extract_text_multiple(website_xpaths)
    place.phone_number = extract_text_multiple(phone_xpaths)
    place.search_keyword = search_keyword
    place.category = category

    # Extract place type with fallbacks
    place_type_xpaths = [
        '//div[@class="LBgpqf"]//button[@class="DkEaL "]',
        '//button[contains(@class, "DkEaL")]',
        '//div[contains(@class, "LBgpqf")]//button'
    ]
    place.place_type = extract_text_multiple(place_type_xpaths)

    # Extract introduction with fallbacks
    intro_xpaths = [
        '//div[@class="WeS02d fontBodyMedium"]//div[@class="PYvSYb "]',
        '//div[contains(@class, "PYvSYb")]',
        '//div[contains(@class, "WeS02d")]'
    ]
    place.introduction = extract_text_multiple(intro_xpaths) or "None Found"

    # Reviews Count with better parsing
    reviews_count_raw = extract_text_multiple(reviews_count_xpaths)
    if reviews_count_raw:
        try:
            # Extract numbers from text like "(1,234 reviews)" or "1,234"
            import re
            numbers = re.findall(r'[\d,]+', reviews_count_raw)
            if numbers:
                temp = numbers[0].replace(',', '').replace('\xa0', '')
                place.reviews_count = int(temp)
        except Exception as e:
            logging.debug(f"Failed to parse reviews count '{reviews_count_raw}': {e}")

    # Reviews Average with better parsing
    reviews_avg_raw = extract_text_multiple(reviews_avg_xpaths)
    if reviews_avg_raw:
        try:
            # Extract rating from text like "4.2" or "4,2"
            import re
            rating_match = re.search(r'(\d+[.,]\d+)', reviews_avg_raw)
            if rating_match:
                temp = rating_match.group(1).replace(',', '.')
                place.reviews_average = float(temp)
        except Exception as e:
            logging.debug(f"Failed to parse reviews average '{reviews_avg_raw}': {e}")

    # Store Info with improved detection
    store_info_xpaths = [
        '//div[@class="LTs0Rc"]',
        '//div[contains(@class, "LTs0Rc")]'
    ]

    for xpath in store_info_xpaths:
        try:
            elements = page.locator(xpath).all()
            for element in elements[:3]:  # Check first 3 elements
                info_raw = element.inner_text().strip()
                if info_raw and '·' in info_raw:
                    parts = info_raw.split('·')
                    if len(parts) > 1:
                        check = parts[1].replace("\n", "").lower()
                        if any(word in check for word in ['shop', 'shopping', 'store']):
                            place.store_shopping = "Yes"
                        if any(word in check for word in ['pickup', 'pick-up', 'takeaway']):
                            place.in_store_pickup = "Yes"
                        if any(word in check for word in ['delivery', 'deliver']):
                            place.store_delivery = "Yes"
        except Exception as e:
            logging.debug(f"Failed to extract store info: {e}")

    # Opening hours with multiple approaches
    opens_xpaths = [
        '//button[contains(@data-item-id, "oh")]//div[contains(@class, "fontBodyMedium")]',
        '//div[@class="MkV9"]//span[@class="ZDu9vd"]//span[2]',
        '//div[contains(@class, "MkV9")]//span[contains(@class, "ZDu9vd")]'
    ]

    opens_at_raw = extract_text_multiple(opens_xpaths)
    if opens_at_raw:
        if '⋅' in opens_at_raw:
            opens = opens_at_raw.split('⋅')
            if len(opens) > 1:
                place.opens_at = opens[1].replace("\u202f", "").strip()
            else:
                place.opens_at = opens_at_raw.replace("\u202f", "").strip()
        else:
            place.opens_at = opens_at_raw.replace("\u202f", "").strip()

    return place


def scrape_single_keyword(search_for: str, max_results: int = None) -> List[Place]:
    """Scrape places for a single keyword with duplicate detection and improved extraction"""
    places: List[Place] = []
    category = get_category_from_keyword(search_for)
    seen_places = set()  # Track duplicates by name + address

    with sync_playwright() as p:
        if platform.system() == "Windows":
            browser_path = r"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
            browser = p.chromium.launch(executable_path=browser_path, headless=False)
        else:
            browser = p.chromium.launch(headless=False)

        page = browser.new_page()

        try:
            page.goto("https://www.google.com/maps/@32.9817464,70.1930781,3.67z?", timeout=60000)
            page.wait_for_timeout(2000)

            # Clear search box completely
            search_input = page.locator('//input[@id="searchboxinput"]')
            search_input.click()
            page.keyboard.press("Control+a")
            page.keyboard.press("Delete")
            page.wait_for_timeout(1000)

            # Enter new search
            search_input.fill(search_for)
            page.wait_for_timeout(1000)
            page.keyboard.press("Enter")

            # Wait for results with better error handling
            try:
                page.wait_for_selector('//a[contains(@href, "https://www.google.com/maps/place")]', timeout=20000)
                page.wait_for_timeout(3000)  # Let initial results load
            except:
                logging.warning(f"No results found for: {search_for}")
                return places

            # Try to hover over first result
            try:
                page.hover('//a[contains(@href, "https://www.google.com/maps/place")]')
                page.wait_for_timeout(1000)
            except:
                logging.warning(f"Could not hover over results for: {search_for}")

            # Scroll to load all results with improved logic
            previously_counted = 0
            no_change_count = 0
            max_no_change = 5  # Increased patience
            scroll_attempts = 0
            max_scroll_attempts = 50  # Prevent infinite scrolling

            while scroll_attempts < max_scroll_attempts:
                # Scroll down
                page.mouse.wheel(0, 8000)
                page.wait_for_timeout(2500)  # Wait for results to load
                scroll_attempts += 1

                try:
                    # Count current results
                    found = page.locator('//a[contains(@href, "https://www.google.com/maps/place")]').count()
                    logging.info(f"[{search_for}] Currently Found: {found} (Scroll: {scroll_attempts})")

                    # Check if we hit the max limit
                    if max_results and found >= max_results:
                        logging.info(f"[{search_for}] Reached max results limit: {max_results}")
                        break

                    # Check if no new results
                    if found == previously_counted:
                        no_change_count += 1
                        if no_change_count >= max_no_change:
                            logging.info(f"[{search_for}] No more results loading after {scroll_attempts} scrolls")
                            break
                    else:
                        no_change_count = 0

                    previously_counted = found

                    # Additional check: try to scroll to load more
                    if no_change_count >= 2:
                        # Try scrolling in the results panel specifically
                        try:
                            results_panel = page.locator('//div[contains(@class, "m6QErb")]')
                            if results_panel.count() > 0:
                                results_panel.first.scroll_into_view_if_needed()
                                page.mouse.wheel(0, 5000)
                                page.wait_for_timeout(2000)
                        except:
                            pass

                except Exception as e:
                    logging.warning(f"Error counting results: {e}")
                    break

            # Get all unique listings
            all_links = page.locator('//a[contains(@href, "https://www.google.com/maps/place")]').all()

            # Remove duplicates by href
            unique_hrefs = {}
            for link in all_links:
                try:
                    href = link.get_attribute('href')
                    if href and href not in unique_hrefs:
                        unique_hrefs[href] = link.locator("xpath=..")
                except:
                    continue

            listings = list(unique_hrefs.values())

            if max_results:
                listings = listings[:max_results]

            total_listings = len(listings)
            logging.info(f"[{search_for}] Total unique listings to extract: {total_listings}")

            # Extract details from each place
            extracted_count = 0
            for idx, listing in enumerate(listings):
                try:
                    # Click on listing
                    listing.click()
                    page.wait_for_timeout(1000)

                    # Wait for place details to load
                    try:
                        page.wait_for_selector('//div[@class="TIHn2 "]//h1[@class="DUwDvf lfPIob"]', timeout=15000)
                        page.wait_for_timeout(2000)  # Let all details load
                    except:
                        logging.warning(f"[{search_for}] Timeout waiting for details on listing {idx + 1}")
                        continue

                    place = extract_place(page, search_for, category)

                    if place.name:
                        # Create unique identifier to check for duplicates
                        place_id = f"{place.name.lower().strip()}|{place.address.lower().strip()}"

                        if place_id not in seen_places:
                            places.append(place)
                            seen_places.add(place_id)
                            extracted_count += 1
                            logging.info(
                                f"[{search_for}] [OK] Extracted {extracted_count}/{total_listings}: {place.name}")
                        else:
                            logging.info(f"[{search_for}] [SKIP] Duplicate skipped: {place.name}")
                    else:
                        logging.warning(f"[{search_for}] [FAIL] No name found for listing {idx + 1}")

                except Exception as e:
                    logging.warning(f"[{search_for}] Failed to extract listing {idx + 1}: {e}")
                    continue

            logging.info(f"[{search_for}] Final count: {len(places)} unique places extracted")

        except Exception as e:
            logging.error(f"[{search_for}] Unexpected error: {e}")
        finally:
            browser.close()

    return places


def create_directory_structure(base_dir: str = "scraping_results") -> str:
    """Create directory structure for organized results"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    main_dir = os.path.join(base_dir, f"malappuram_businesses_{timestamp}")

    categories = ['Food_Businesses', 'Event_Catering', 'Wholesale_Frozen', 'Specialty_Food', 'Large_Scale_Buyers',
                  'Other']

    os.makedirs(main_dir, exist_ok=True)
    for category in categories:
        os.makedirs(os.path.join(main_dir, category), exist_ok=True)

    return main_dir


def save_places_to_csv(places: List[Place], output_path: str, append: bool = False):
    """Save places to CSV with error handling and duplicate removal"""
    if not places:
        logging.warning("No places to save")
        return

    df = pd.DataFrame([asdict(place) for place in places])

    # Ensure directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Handle appending with duplicate checking
    if append and os.path.isfile(output_path):
        # Read existing data
        try:
            existing_df = pd.read_csv(output_path)
            # Combine with new data
            combined_df = pd.concat([existing_df, df], ignore_index=True)

            # Remove duplicates based on name + address + phone
            combined_df['duplicate_key'] = (
                    combined_df['name'].fillna('').str.lower().str.strip() + "|" +
                    combined_df['address'].fillna('').str.lower().str.strip() + "|" +
                    combined_df['phone_number'].fillna('').str.strip()
            )

            # Keep first occurrence of each duplicate
            combined_df = combined_df.drop_duplicates(subset=['duplicate_key'], keep='first')
            combined_df = combined_df.drop(columns=['duplicate_key'])

            df = combined_df
            append = False  # Write complete file now
            logging.info(f"Removed duplicates, final count: {len(df)}")

        except Exception as e:
            logging.warning(f"Error handling existing file: {e}, will append normally")

    # Remove columns that are all the same value (only for non-append writes)
    if not append:
        cols_to_drop = []
        for column in df.columns:
            if df[column].nunique() <= 1:
                cols_to_drop.append(column)
        if cols_to_drop:
            df = df.drop(columns=cols_to_drop)
            logging.info(f"Removed constant columns: {cols_to_drop}")

    file_exists = os.path.isfile(output_path)
    mode = "a" if append else "w"
    header = not (append and file_exists)

    df.to_csv(output_path, index=False, mode=mode, header=header)
    logging.info(f"Saved {len(df)} places to {output_path} (duplicates removed)")


def batch_scrape_keywords(keywords: List[str], base_dir: str = "scraping_results",
                          max_per_keyword: int = None, start_from: int = 0) -> Dict:
    """Scrape all keywords and organize by category"""

    # Create directory structure
    main_dir = create_directory_structure(base_dir)
    log_file = os.path.join(main_dir, "scraping_log.txt")
    setup_logging(log_file)

    # Progress tracking
    progress_file = os.path.join(main_dir, "progress.json")
    results_summary = {
        'total_keywords': len(keywords),
        'completed': 0,
        'failed': 0,
        'total_places': 0,
        'categories': {},
        'start_time': datetime.now().isoformat(),
        'last_completed_keyword': '',
        'failed_keywords': []
    }

    logging.info(f"Starting batch scrape of {len(keywords)} keywords")
    logging.info(f"Results will be saved to: {main_dir}")
    logging.info(f"Starting from keyword index: {start_from}")

    for idx, keyword in enumerate(keywords[start_from:], start_from):
        try:
            logging.info(f"\n{'=' * 50}")
            logging.info(f"Processing {idx + 1}/{len(keywords)}: {keyword}")
            logging.info(f"{'=' * 50}")

            places = scrape_single_keyword(keyword, max_per_keyword)

            if places:
                category = get_category_from_keyword(keyword)

                # Create filename
                safe_keyword = keyword.replace(' ', '_').replace('/', '_')
                filename = f"{safe_keyword}.csv"
                filepath = os.path.join(main_dir, category, filename)

                # Save to category folder
                save_places_to_csv(places, filepath)

                # Also append to master category file
                master_file = os.path.join(main_dir, category, f"{category}_all.csv")
                save_places_to_csv(places, master_file, append=True)

                # Update summary
                results_summary['total_places'] += len(places)
                if category not in results_summary['categories']:
                    results_summary['categories'][category] = 0
                results_summary['categories'][category] += len(places)

                logging.info(f"{keyword}: Found {len(places)} places")
            else:
                logging.warning(f"{keyword}: No places found")

            results_summary['completed'] += 1
            results_summary['last_completed_keyword'] = keyword

            # Save progress
            with open(progress_file, 'w') as f:
                json.dump(results_summary, f, indent=2)

            # Small delay between searches
            time.sleep(2)

        except KeyboardInterrupt:
            logging.info("Scraping interrupted by user")
            break
        except Exception as e:
            logging.error(f"Failed to process {keyword}: {e}")
            results_summary['failed'] += 1
            results_summary['failed_keywords'].append(keyword)

    # Final summary
    results_summary['end_time'] = datetime.now().isoformat()
    with open(progress_file, 'w') as f:
        json.dump(results_summary, f, indent=2)

    # Create final summary report
    summary_file = os.path.join(main_dir, "SUMMARY_REPORT.txt")
    with open(summary_file, 'w') as f:
        f.write("MALAPPURAM BUSINESS SCRAPING SUMMARY\n")
        f.write("=" * 50 + "\n\n")
        f.write(f"Total Keywords Processed: {results_summary['completed']}/{results_summary['total_keywords']}\n")
        f.write(f"Total Places Found: {results_summary['total_places']}\n")
        f.write(f"Failed Keywords: {results_summary['failed']}\n\n")

        f.write("RESULTS BY CATEGORY:\n")
        f.write("-" * 30 + "\n")
        for category, count in results_summary['categories'].items():
            f.write(f"{category}: {count} places\n")

        if results_summary['failed_keywords']:
            f.write(f"\nFAILED KEYWORDS:\n")
            f.write("-" * 20 + "\n")
            for failed in results_summary['failed_keywords']:
                f.write(f"- {failed}\n")

    logging.info(f"\n[COMPLETE] SCRAPING FINISHED!")
    logging.info(f"[RESULTS] Results saved to: {main_dir}")
    logging.info(f"[STATS] Total places found: {results_summary['total_places']}")
    logging.info(f"[PROGRESS] Completed: {results_summary['completed']}/{results_summary['total_keywords']}")

    return results_summary


def main():
    # Your keywords list
    keywords = [
        # Food Businesses
        "bakery malappuram", "bakery manjeri", "bakery perinthalmanna", "bakery nilambur",
        "bakery tirur", "bakery ponnani", "bakery kondotty", "bakery tirurangadi",
        "hotel malappuram", "hotel manjeri", "hotel perinthalmanna", "hotel nilambur",
        "hotel tirur", "hotel ponnani", "hotel kondotty", "hotel tirurangadi",
        "restaurant malappuram", "restaurant manjeri", "restaurant perinthalmanna", "restaurant nilambur",
        "restaurant tirur", "restaurant ponnani", "restaurant kondotty", "restaurant tirurangadi",
        "tea shop malappuram", "tea shop manjeri", "tea shop perinthalmanna", "tea shop nilambur",
        "tea shop tirur", "tea shop ponnani", "tea shop kondotty", "tea shop tirurangadi",
        "snacks shop malappuram", "snacks shop manjeri", "snacks shop perinthalmanna", "snacks shop nilambur",
        "snacks shop tirur", "snacks shop ponnani", "snacks shop kondotty", "snacks shop tirurangadi",
        # Event & Catering
        "catering malappuram", "catering manjeri", "catering perinthalmanna", "catering nilambur",
        "catering tirur", "catering ponnani", "catering kondotty", "catering tirurangadi",
        "event management malappuram", "event management manjeri", "event management perinthalmanna",
        "event management nilambur",
        "event management tirur", "event management ponnani", "event management kondotty",
        "event management tirurangadi",
        # Wholesale & Frozen Food
        "wholesale snacks malappuram", "wholesale snacks manjeri", "wholesale snacks perinthalmanna",
        "wholesale snacks nilambur",
        "wholesale snacks tirur", "wholesale snacks ponnani", "wholesale snacks kondotty",
        "wholesale snacks tirurangadi",
        "frozen food malappuram", "frozen food manjeri", "frozen food perinthalmanna", "frozen food nilambur",
        "frozen food tirur", "frozen food ponnani", "frozen food kondotty", "frozen food tirurangadi",
        # Specialty Food & Biryani
        "biryani malappuram", "biryani manjeri", "biryani perinthalmanna", "biryani nilambur",
        "biryani tirur", "biryani ponnani", "biryani kondotty", "biryani tirurangadi",
        "fast food malappuram", "fast food manjeri", "fast food perinthalmanna", "fast food nilambur",
        "fast food tirur", "fast food ponnani", "fast food kondotty", "fast food tirurangadi",
        # Large-Scale Buyers
        "canteen malappuram", "canteen manjeri", "canteen perinthalmanna", "canteen nilambur",
        "canteen tirur", "canteen ponnani", "canteen kondotty", "canteen tirurangadi",
        "mess malappuram", "mess manjeri", "mess perinthalmanna", "mess nilambur"
    ]

    parser = argparse.ArgumentParser(description="Automated Google Maps Business Scraper for Malappuram")
    parser.add_argument("--max-per-keyword", type=int, help="Maximum results per keyword (default: unlimited)")
    parser.add_argument("--start-from", type=int, default=0, help="Start from keyword index (for resuming)")
    parser.add_argument("--base-dir", type=str, default="scraping_results", help="Base directory for results")
    parser.add_argument("--test-mode", action="store_true", help="Test with first 3 keywords only")

    args = parser.parse_args()

    if args.test_mode:
        keywords = keywords[:3]
        print(f"[TEST] TEST MODE: Processing only {len(keywords)} keywords")

    print(f"[START] Starting automated scraping of {len(keywords)} keywords...")
    print(f"[OUTPUT] Results will be organized in: {args.base_dir}")

    if args.max_per_keyword:
        print(f"[LIMIT] Max results per keyword: {args.max_per_keyword}")

    if args.start_from > 0:
        print(f"[RESUME] Resuming from keyword index: {args.start_from}")

    summary = batch_scrape_keywords(
        keywords=keywords,
        base_dir=args.base_dir,
        max_per_keyword=args.max_per_keyword,
        start_from=args.start_from
    )

    print(f"\n[COMPLETE] MISSION COMPLETE!")
    print(f"Total businesses found: {summary['total_places']}")


if __name__ == "__main__":
    main()