import logging
from typing import List, Optional, Dict
from playwright.sync_api import sync_playwright, Page, TimeoutError
from dataclasses import dataclass, asdict
import pandas as pd
import argparse
import platform
import time
import os
from datetime import datetime
import json
import re


@dataclass
class Place:
    name: str = ""
    address: str = ""
    website: str = ""
    phone_number: str = ""
    google_maps_url: str = ""  # NEW: Direct Google Maps URL
    place_id: str = ""  # NEW: Google Place ID from URL
    reviews_count: Optional[int] = None
    reviews_average: Optional[float] = None
    price_range: str = ""  # NEW: Price range (₹, ₹₹, ₹₹₹, etc.)
    store_shopping: str = "No"
    in_store_pickup: str = "No"
    store_delivery: str = "No"
    dine_in: str = "No"  # NEW: Dine-in option
    takeaway: str = "No"  # NEW: Takeaway option
    reservations: str = "No"  # NEW: Accepts reservations
    wheelchair_accessible: str = "Unknown"  # NEW: Accessibility
    place_type: str = ""
    opens_at: str = ""
    full_hours: str = ""  # NEW: Complete opening hours
    popular_times: str = ""  # NEW: Popular times info
    introduction: str = ""
    services_offered: str = ""  # NEW: List of services
    amenities: str = ""  # NEW: Available amenities
    photos_count: Optional[int] = None  # NEW: Number of photos
    verified_business: str = "Unknown"  # NEW: Business verification status
    years_in_business: str = ""  # NEW: How long in business
    owner_info: str = ""  # NEW: Owner/management info
    coordinates: str = ""  # NEW: Lat, Lng coordinates
    search_keyword: str = ""
    category: str = ""
    scraped_at: str = ""  # NEW: Timestamp when scraped


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

    import sys
    if sys.platform.startswith('win'):
        try:
            import codecs
            sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer)
            sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer)
        except:
            pass


def get_category_from_keyword(keyword: str) -> str:
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


def extract_coordinates_from_url(url: str) -> str:
    """Extract coordinates from Google Maps URL"""
    try:
        # Pattern to match coordinates in URL
        coord_pattern = r'@(-?\d+\.\d+),(-?\d+\.\d+)'
        match = re.search(coord_pattern, url)
        if match:
            lat, lng = match.groups()
            return f"{lat}, {lng}"
    except Exception as e:
        logging.debug(f"Failed to extract coordinates from URL: {e}")
    return ""


def extract_place_id_from_url(url: str) -> str:
    """Extract place ID from Google Maps URL"""
    try:
        # Pattern to match place ID in URL
        place_id_pattern = r'place/[^/]+/data=.*?!3m1!4b1!4m\d+!3m\d+!1s([^!]+)'
        match = re.search(place_id_pattern, url)
        if match:
            return match.group(1)

        # Alternative pattern
        place_id_pattern2 = r'data=.*?1s([^!]+)'
        match2 = re.search(place_id_pattern2, url)
        if match2:
            return match2.group(1)
    except Exception as e:
        logging.debug(f"Failed to extract place ID from URL: {e}")
    return ""


def extract_place(page: Page, search_keyword: str = "", category: str = "") -> Place:
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
        for xpath in xpaths:
            try:
                elements = page.locator(xpath)
                if elements.count() > 0:
                    text = elements.first.inner_text().strip()
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
    place.scraped_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # NEW: Extract Google Maps URL and Place ID
    try:
        current_url = page.url
        place.google_maps_url = current_url
        place.place_id = extract_place_id_from_url(current_url)
        place.coordinates = extract_coordinates_from_url(current_url)
    except Exception as e:
        logging.debug(f"Failed to extract URL info: {e}")

    # Place type
    place_type_xpaths = [
        '//div[@class="LBgpqf"]//button[@class="DkEaL "]',
        '//button[contains(@class, "DkEaL")]',
        '//div[contains(@class, "LBgpqf")]//button'
    ]
    place.place_type = extract_text_multiple(place_type_xpaths)

    # Introduction
    intro_xpaths = [
        '//div[@class="WeS02d fontBodyMedium"]//div[@class="PYvSYb "]',
        '//div[contains(@class, "PYvSYb")]',
        '//div[contains(@class, "WeS02d")]'
    ]
    place.introduction = extract_text_multiple(intro_xpaths) or "None Found"

    # NEW: Price Range
    price_xpaths = [
        '//span[contains(@aria-label, "Price") or contains(@aria-label, "price")]',
        '//span[contains(text(), "₹")]'
    ]
    place.price_range = extract_text_multiple(price_xpaths)

    # Reviews Count
    reviews_count_raw = extract_text_multiple(reviews_count_xpaths)
    if reviews_count_raw:
        try:
            numbers = re.findall(r'[\d,]+', reviews_count_raw)
            if numbers:
                temp = numbers[0].replace(',', '').replace('\xa0', '')
                place.reviews_count = int(temp)
        except Exception as e:
            logging.debug(f"Failed to parse reviews count '{reviews_count_raw}': {e}")

    # Reviews Average
    reviews_avg_raw = extract_text_multiple(reviews_avg_xpaths)
    if reviews_avg_raw:
        try:
            rating_match = re.search(r'(\d+[.,]\d+)', reviews_avg_raw)
            if rating_match:
                temp = rating_match.group(1).replace(',', '.')
                place.reviews_average = float(temp)
        except Exception as e:
            logging.debug(f"Failed to parse reviews average '{reviews_avg_raw}': {e}")

    # Enhanced Store/Service Info
    store_info_xpaths = [
        '//div[@class="LTs0Rc"]',
        '//div[contains(@class, "LTs0Rc")]',
        '//div[contains(@class, "etWJQ")]//div[contains(@class, "BNeawe")]'
    ]

    services_list = []
    amenities_list = []

    for xpath in store_info_xpaths:
        try:
            elements = page.locator(xpath)
            element_count = elements.count()
            for i in range(min(element_count, 10)):  # Check up to 10 elements
                try:
                    element = elements.nth(i)
                    info_raw = element.inner_text().strip()
                    if info_raw and '·' in info_raw:
                        parts = info_raw.split('·')
                        if len(parts) > 1:
                            check = parts[1].replace("\n", "").lower()

                            # Existing checks
                            if any(word in check for word in ['shop', 'shopping', 'store']):
                                place.store_shopping = "Yes"
                            if any(word in check for word in ['pickup', 'pick-up', 'takeaway']):
                                place.in_store_pickup = "Yes"
                                place.takeaway = "Yes"
                            if any(word in check for word in ['delivery', 'deliver']):
                                place.store_delivery = "Yes"

                            # NEW: Enhanced service detection
                            if any(word in check for word in ['dine-in', 'dine in', 'dining']):
                                place.dine_in = "Yes"
                            if any(word in check for word in ['reservation', 'reservations', 'booking']):
                                place.reservations = "Yes"
                            if any(word in check for word in ['wheelchair', 'accessible', 'accessibility']):
                                place.wheelchair_accessible = "Yes"
                            if any(word in check for word in ['verified', 'google verified']):
                                place.verified_business = "Yes"

                            # Collect services and amenities
                            services_list.append(check)
                except Exception as e:
                    logging.debug(f"Failed to extract from element {i}: {e}")
                    continue

        except Exception as e:
            logging.debug(f"Failed to extract enhanced store info: {e}")

    place.services_offered = "; ".join(set(services_list)) if services_list else ""

    # NEW: Extract photos count
    try:
        photos_elements = page.locator(
            '//button[contains(@aria-label, "photo") or contains(@aria-label, "Photo")]')
        element_count = photos_elements.count()

        for i in range(element_count):
            try:
                elem = photos_elements.nth(i)
                aria_label = elem.get_attribute('aria-label') or ""
                if 'photo' in aria_label.lower():
                    photo_numbers = re.findall(r'(\d+)', aria_label)
                    if photo_numbers:
                        place.photos_count = int(photo_numbers[0])
                        break
            except Exception as e:
                logging.debug(f"Failed to extract photos from element {i}: {e}")
                continue
    except Exception as e:
        logging.debug(f"Failed to extract photos count: {e}")

    # Enhanced Opening hours
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
                place.full_hours = opens_at_raw.replace("\u202f", "").strip()
            else:
                place.opens_at = opens_at_raw.replace("\u202f", "").strip()
                place.full_hours = opens_at_raw.replace("\u202f", "").strip()
        else:
            place.opens_at = opens_at_raw.replace("\u202f", "").strip()
            place.full_hours = opens_at_raw.replace("\u202f", "").strip()

    # NEW: Extract popular times info
    try:
        popular_times_elem = page.locator(
            '//div[contains(text(), "Popular times") or contains(text(), "popular times")]')
        if popular_times_elem.count() > 0:
            place.popular_times = "Available"
        else:
            place.popular_times = "Not Available"
    except:
        place.popular_times = "Not Available"

    # NEW: Extract business verification and additional info
    try:
        # Check for verified badge
        verified_elements = page.locator('//*[contains(text(), "verified") or contains(text(), "Verified")]')
        if verified_elements.count() > 0:
            place.verified_business = "Yes"
    except:
        pass

    return place


def scrape_single_keyword(search_for: str, max_results: int = None) -> List[Place]:
    places: List[Place] = []
    category = get_category_from_keyword(search_for)
    seen_places = set()

    with sync_playwright() as p:
        try:
            if platform.system() == "Windows":
                browser_path = r"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
                if os.path.exists(browser_path):
                    browser = p.chromium.launch(executable_path=browser_path, headless=True)
                else:
                    logging.warning("Chrome not found at expected path, using default browser")
                    browser = p.chromium.launch(headless=True)
            else:
                browser = p.chromium.launch(headless=True)

            page = browser.new_page()

            try:
                page.goto("https://www.google.com/maps/@32.9817464,70.1930781,3.67z?", timeout=30000)
                page.wait_for_timeout(2000)  # Increased wait time

                # Search
                search_input = page.locator('//input[@id="searchboxinput"]')
                search_input.click()
                page.keyboard.press("Control+a")
                page.keyboard.press("Delete")
                page.wait_for_timeout(500)

                search_input.fill(search_for)
                page.wait_for_timeout(1000)  # Increased wait time
                page.keyboard.press("Enter")

                # Wait for results with better error handling
                try:
                    page.wait_for_selector('//a[contains(@href, "https://www.google.com/maps/place")]', timeout=20000)
                    page.wait_for_timeout(3000)  # Increased wait time
                except TimeoutError:
                    logging.warning(f"No results found for: {search_for}")
                    return places

                # Hover with error handling
                try:
                    first_result = page.locator('//a[contains(@href, "https://www.google.com/maps/place")]').first
                    if first_result.count() > 0:
                        first_result.hover()
                        page.wait_for_timeout(500)
                except:
                    pass

                # Improved scrolling logic
                previously_counted = 0
                no_change_count = 0
                max_no_change = 8  # Increased threshold
                scroll_attempts = 0
                max_scroll_attempts = 50

                while scroll_attempts < max_scroll_attempts:
                    try:
                        page.mouse.wheel(0, 5000)
                        page.wait_for_timeout(2000)  # Increased wait time
                        scroll_attempts += 1

                        found = page.locator('//a[contains(@href, "https://www.google.com/maps/place")]').count()
                        logging.info(f"[{search_for}] Found: {found} (Scroll: {scroll_attempts})")

                        if max_results and found >= max_results:
                            logging.info(f"[{search_for}] Reached max results: {max_results}")
                            break

                        if found == previously_counted:
                            no_change_count += 1
                            if no_change_count >= max_no_change:
                                logging.info(f"[{search_for}] No more results after {scroll_attempts} scrolls")
                                break
                        else:
                            no_change_count = 0

                        previously_counted = found

                    except Exception as e:
                        logging.warning(f"Error during scrolling: {e}")
                        break

                # Get all listings with improved duplicate handling
                all_links = page.locator('//a[contains(@href, "https://www.google.com/maps/place")]').all()

                # Remove duplicates by href
                unique_hrefs = {}
                for link in all_links:
                    try:
                        href = link.get_attribute('href')
                        if href and href not in unique_hrefs:
                            parent_element = link.locator("xpath=..")
                            if parent_element.count() > 0:
                                unique_hrefs[href] = parent_element
                    except Exception as e:
                        logging.debug(f"Error processing link: {e}")
                        continue

                listings = list(unique_hrefs.values())

                if max_results:
                    listings = listings[:max_results]

                total_listings = len(listings)
                logging.info(f"[{search_for}] Total unique listings: {total_listings}")

                # Extract from each listing with improved error handling
                extracted_count = 0
                for idx, listing in enumerate(listings):
                    try:
                        # Try clicking multiple times with better error handling
                        click_success = False
                        for attempt in range(5):  # Increased attempts
                            try:
                                listing.click(timeout=10000)
                                page.wait_for_timeout(1500)  # Increased wait time
                                click_success = True
                                break
                            except Exception as e:
                                logging.debug(f"Click attempt {attempt + 1} failed: {e}")
                                if attempt < 4:
                                    page.wait_for_timeout(1000)

                        if not click_success:
                            logging.warning(f"[{search_for}] Failed to click listing {idx + 1}")
                            continue

                        # Try waiting for details with better error handling
                        details_loaded = False
                        for attempt in range(5):  # Increased attempts
                            try:
                                page.wait_for_selector('//div[@class="TIHn2 "]//h1[@class="DUwDvf lfPIob"]',
                                                       timeout=15000)
                                page.wait_for_timeout(3000)  # Increased wait time for enhanced extraction
                                details_loaded = True
                                break
                            except TimeoutError:
                                if attempt < 4:
                                    page.wait_for_timeout(2000)

                        # Extract with enhanced data
                        place = extract_place(page, search_for, category)

                        # Save even partial data with improved validation
                        if place.name or place.address or place.phone_number:
                            # Better duplicate detection
                            place_id = f"{place.name.lower().strip()}|{place.address.lower().strip()}|{place.phone_number.strip()}"

                            if place_id not in seen_places:
                                places.append(place)
                                seen_places.add(place_id)
                                extracted_count += 1
                                logging.info(
                                    f"[{search_for}] [OK] {extracted_count}/{total_listings}: {place.name or 'Partial data'}")
                            else:
                                logging.info(f"[{search_for}] [SKIP] Duplicate: {place.name}")
                        else:
                            logging.warning(f"[{search_for}] [FAIL] No useful data for listing {idx + 1}")

                    except Exception as e:
                        logging.warning(f"[{search_for}] Failed listing {idx + 1}: {e}")
                        continue

                logging.info(f"[{search_for}] FINAL: {len(places)} places extracted")

            except Exception as e:
                logging.error(f"[{search_for}] ERROR during page operations: {e}")
            finally:
                page.close()

        except Exception as e:
            logging.error(f"[{search_for}] ERROR during browser setup: {e}")
        finally:
            try:
                browser.close()
            except:
                pass

    return places


def create_directory_structure(base_dir: str = "scraping_results") -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    main_dir = os.path.join(base_dir, f"malappuram_businesses_enhanced_{timestamp}")

    categories = ['Food_Businesses', 'Event_Catering', 'Wholesale_Frozen', 'Specialty_Food', 'Large_Scale_Buyers',
                  'Other']

    os.makedirs(main_dir, exist_ok=True)
    for category in categories:
        os.makedirs(os.path.join(main_dir, category), exist_ok=True)

    return main_dir


def save_places_to_csv(places: List[Place], output_path: str, append: bool = False):
    if not places:
        logging.warning("No places to save")
        return

    try:
        df = pd.DataFrame([asdict(place) for place in places])

        # Reorder columns to put important new fields first
        column_order = [
            'name', 'address', 'phone_number', 'google_maps_url', 'place_id',
            'coordinates', 'website', 'place_type', 'category', 'reviews_average',
            'reviews_count', 'price_range', 'opens_at', 'full_hours',
            'store_shopping', 'in_store_pickup', 'store_delivery', 'dine_in',
            'takeaway', 'reservations', 'wheelchair_accessible', 'verified_business',
            'introduction', 'services_offered', 'amenities', 'photos_count',
            'popular_times', 'years_in_business', 'owner_info', 'search_keyword',
            'scraped_at'
        ]

        # Only include columns that exist in the dataframe
        available_columns = [col for col in column_order if col in df.columns]
        missing_columns = [col for col in df.columns if col not in available_columns]
        final_column_order = available_columns + missing_columns

        df = df[final_column_order]

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        if append and os.path.isfile(output_path):
            try:
                existing_df = pd.read_csv(output_path)
                combined_df = pd.concat([existing_df, df], ignore_index=True)

                # Remove duplicates using enhanced logic
                combined_df['duplicate_key'] = (
                        combined_df['name'].fillna('').str.lower().str.strip() + "|" +
                        combined_df['address'].fillna('').str.lower().str.strip() + "|" +
                        combined_df['google_maps_url'].fillna('').str.strip()
                )

                combined_df = combined_df.drop_duplicates(subset=['duplicate_key'], keep='first')
                combined_df = combined_df.drop(columns=['duplicate_key'])

                df = combined_df
                append = False
                logging.info(f"Removed duplicates, final count: {len(df)}")

            except Exception as e:
                logging.warning(f"Error handling existing file: {e}")

        file_exists = os.path.isfile(output_path)
        mode = "a" if append else "w"
        header = not (append and file_exists)

        df.to_csv(output_path, index=False, mode=mode, header=header, encoding='utf-8')
        logging.info(f"Saved {len(df)} places to {output_path}")

    except Exception as e:
        logging.error(f"Error saving to CSV: {e}")


def batch_scrape_keywords(keywords: List[str], base_dir: str = "scraping_results",
                          max_per_keyword: int = None, start_from: int = 0) -> Dict:
    main_dir = create_directory_structure(base_dir)
    log_file = os.path.join(main_dir, "scraping_log.txt")
    setup_logging(log_file)

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

    logging.info(f"Starting ENHANCED batch scrape of {len(keywords)} keywords")
    logging.info(f"Results will be saved to: {main_dir}")
    logging.info(f"Starting from keyword index: {start_from}")
    logging.info(f"NEW FEATURES: Google Maps URL, Place ID, Coordinates, Enhanced Services, Photos Count, etc.")

    for idx, keyword in enumerate(keywords[start_from:], start_from):
        try:
            logging.info(f"\n{'=' * 50}")
            logging.info(f"Processing {idx + 1}/{len(keywords)}: {keyword}")
            logging.info(f"{'=' * 50}")

            places = scrape_single_keyword(keyword, max_per_keyword)

            if places:
                category = get_category_from_keyword(keyword)

                safe_keyword = re.sub(r'[^\w\s-]', '', keyword).replace(' ', '_').replace('/', '_')
                filename = f"{safe_keyword}.csv"
                filepath = os.path.join(main_dir, category, filename)

                save_places_to_csv(places, filepath)

                master_file = os.path.join(main_dir, category, f"{category}_all.csv")
                save_places_to_csv(places, master_file, append=True)

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
            progress_file = os.path.join(main_dir, "progress.json")
            with open(progress_file, 'w', encoding='utf-8') as f:
                json.dump(results_summary, f, indent=2, ensure_ascii=False)

            time.sleep(2)  # Increased sleep time

        except KeyboardInterrupt:
            logging.info("Scraping interrupted by user")
            break
        except Exception as e:
            logging.error(f"Failed to process {keyword}: {e}")
            results_summary['failed'] += 1
            results_summary['failed_keywords'].append(keyword)

    # Final summary
    results_summary['end_time'] = datetime.now().isoformat()
    progress_file = os.path.join(main_dir, "progress.json")
    with open(progress_file, 'w', encoding='utf-8') as f:
        json.dump(results_summary, f, indent=2, ensure_ascii=False)

    summary_file = os.path.join(main_dir, "ENHANCED_SUMMARY_REPORT.txt")
    with open(summary_file, 'w', encoding='utf-8') as f:
        f.write("ENHANCED MALAPPURAM BUSINESS SCRAPING SUMMARY\n")
        f.write("=" * 60 + "\n\n")
        f.write("NEW FEATURES ADDED:\n")
        f.write("- Google Maps URL for each business\n")
        f.write("- Place ID extraction\n")
        f.write("- GPS Coordinates (Lat, Lng)\n")
        f.write("- Enhanced service detection (dine-in, takeaway, reservations, etc.)\n")
        f.write("- Price range information\n")
        f.write("- Photos count\n")
        f.write("- Business verification status\n")
        f.write("- Complete opening hours\n")
        f.write("- Popular times availability\n")
        f.write("- Wheelchair accessibility\n")
        f.write("- Scraping timestamp\n\n")

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

    return results_summary


# Keywords list
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
    "mess malappuram", "mess manjeri", "mess perinthalmanna", "mess nilambur",

    # Large-Scale Buyers - Supermarkets
    "supermarket malappuram", "supermarket manjeri", "supermarket perinthalmanna", "supermarket nilambur",
    "supermarket tirur", "supermarket ponnani", "supermarket kondotty", "supermarket tirurangadi",

    # Large-Scale Buyers - Grocery Stores
    "grocery store malappuram", "grocery store manjeri", "grocery store perinthalmanna", "grocery store nilambur",
    "grocery store tirur", "grocery store ponnani", "grocery store kondotty", "grocery store tirurangadi",

]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Enhanced Google Maps Scraper for Malappuram Businesses')
    parser.add_argument('--max-results', type=int, default=None,
                        help='Maximum results per keyword (default: unlimited)')
    parser.add_argument('--start-from', type=int, default=0,
                        help='Start from keyword index (for resuming)')
    parser.add_argument('--output-dir', type=str, default='scraping_results',
                        help='Output directory (default: scraping_results)')
    parser.add_argument('--single-keyword', type=str, default=None,
                        help='Test with single keyword instead of full batch')

    args = parser.parse_args()

    print("🚀 Enhanced Malappuram Business Scraper")
    print("=" * 50)
    print("NEW FEATURES:")
    print("✅ Google Maps URLs")
    print("✅ Place IDs & Coordinates")
    print("✅ Enhanced Services Detection")
    print("✅ Photos Count & Price Range")
    print("✅ Business Verification Status")
    print("✅ Complete Opening Hours")
    print("✅ Accessibility Information")
    print("=" * 50)

    if args.single_keyword:
        # Test mode with single keyword
        print(f"\n🧪 TEST MODE: Scraping '{args.single_keyword}'")
        setup_logging()

        places = scrape_single_keyword(args.single_keyword, args.max_results)

        if places:
            print(f"\n✅ Found {len(places)} places!")

            # Save test results
            test_dir = os.path.join(args.output_dir, "test_results")
            os.makedirs(test_dir, exist_ok=True)

            safe_keyword = re.sub(r'[^\w\s-]', '', args.single_keyword).replace(' ', '_').replace('/', '_')
            test_file = os.path.join(test_dir, f"test_{safe_keyword}.csv")
            save_places_to_csv(places, test_file)

            print(f"💾 Results saved to: {test_file}")

            # Show sample data
            print(f"\n📋 Sample Results:")
            print("-" * 30)
            for i, place in enumerate(places[:3]):
                print(f"{i + 1}. {place.name}")
                print(f"   📍 {place.address}")
                print(f"   📞 {place.phone_number}")
                print(f"   🌐 {place.website}")
                print(f"   ⭐ {place.reviews_average} ({place.reviews_count} reviews)")
                print(f"   🔗 {place.google_maps_url[:50]}..." if place.google_maps_url else "   🔗 No URL")
                print()
        else:
            print("❌ No places found!")

    else:
        # Full batch mode
        print(f"\n🚀 FULL BATCH MODE")
        print(f"📊 Total keywords: {len(keywords)}")
        print(f"📁 Output directory: {args.output_dir}")
        print(f"🎯 Max per keyword: {args.max_results or 'Unlimited'}")
        print(f"▶️  Starting from index: {args.start_from}")

        # Confirm before starting
        confirm = input("\n❓ Start scraping? (y/N): ").strip().lower()
        if confirm != 'y':
            print("❌ Scraping cancelled.")
            exit(0)

        print("\n🏃‍♂️ Starting batch scrape...")

        try:
            results = batch_scrape_keywords(
                keywords=keywords,
                base_dir=args.output_dir,
                max_per_keyword=args.max_results,
                start_from=args.start_from
            )

            print(f"\n🎉 SCRAPING COMPLETED!")
            print(f"✅ Completed: {results['completed']}/{results['total_keywords']}")
            print(f"📊 Total places: {results['total_places']}")
            print(f"❌ Failed: {results['failed']}")

            if results['categories']:
                print(f"\n📈 Results by category:")
                for category, count in results['categories'].items():
                    print(f"   {category}: {count} places")

            print(f"\n📁 Check results in the output directory!")

        except KeyboardInterrupt:
            print(f"\n⚠️  Scraping interrupted by user")
            print(f"✅ Progress saved - you can resume using --start-from")
        except Exception as e:
            print(f"\n❌ Error during scraping: {e}")
            logging.error(f"Main execution error: {e}")

        print(f"\n🏁 Script finished!")