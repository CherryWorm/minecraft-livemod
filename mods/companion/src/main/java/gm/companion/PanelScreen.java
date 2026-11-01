package gm.companion;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.mojang.blaze3d.platform.InputConstants;
import net.minecraft.client.gui.GuiGraphicsExtractor;
import net.minecraft.client.gui.components.EditBox;
import net.minecraft.client.gui.screens.inventory.AbstractContainerScreen;
import net.minecraft.client.gui.screens.inventory.InventoryScreen;
import net.minecraft.client.input.KeyEvent;
import net.minecraft.client.input.MouseButtonEvent;
import net.minecraft.client.renderer.RenderPipelines;
import net.minecraft.client.resources.sounds.SimpleSoundInstance;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.network.chat.Component;
import net.minecraft.resources.Identifier;
import net.minecraft.sounds.SoundEvents;
import net.minecraft.util.FormattedCharSequence;
import net.minecraft.world.Container;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.EntitySpawnReason;
import net.minecraft.world.entity.EntityType;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.player.Inventory;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.inventory.ChestMenu;
import net.minecraft.world.inventory.ContainerInput;
import net.minecraft.world.inventory.Slot;
import net.minecraft.world.item.ItemStack;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Draws a panel the way the server described it, over the chest menu it really is. The real slots are moved to where it says, and the
 * rest of the chest, which holds pictures of everything for a client with no companion, is hidden. Clicking a button clicks its picture,
 * so the server sees exactly what it would from a plain chest, and nothing here decides anything.
 */
final class PanelScreen extends AbstractContainerScreen<ChestMenu> {
	private static final int DEFAULT_WIDTH = 176;
	private static final int DEFAULT_HEIGHT = 166;
	private static final int CHEST_ROW = 9;
	private static final int SLOT_SIZE = 18;
	private static final int HOTBAR_GAP = 4;
	private static final int MAIN_ROWS = 3;
	private static final int INVENTORY_HEIGHT = 82;
	private static final int ROW_HEIGHT = 18;
	private static final int TAB_HEIGHT = 16;
	private static final int TAB_PADDING = 10;
	private static final int ICON_SIZE = 16;
	private static final int TEXT_HEIGHT = 9;
	// The colours of the game's own containers.
	private static final int PANEL_COLOUR = 0xFFC6C6C6;
	private static final int OUTLINE = 0xFF000000;
	private static final int EDGE_DARK = 0xFF555555;
	private static final int EDGE_LIGHT = 0xFFFFFFFF;
	private static final int SLOT_COLOUR = 0xFF8B8B8B;
	private static final int SLOT_SHADE = 0xFF373737;
	private static final int TAB_HOVER = 0xFFA8A8A8;
	private static final int TEXT_ON_BUTTON = 0xFFFFFFFF;
	private static final int TEXT_OFF = 0xFFA0A0A0;
	private static final int TEXT_ON_PANEL = 0xFF404040;
	private static final int BAR_COLOUR = 0xFF55CC55;
	private static final int SCROLLER_WIDTH = 6;
	private static final int SMALLEST_SCROLLER = 8;
	private static final int INVENTORY_LABEL_ABOVE = 12;
	private static final Identifier SLOT_SPRITE = Identifier.withDefaultNamespace("container/slot");
	private static final Identifier BUTTON_SPRITE = Identifier.withDefaultNamespace("widget/button");
	private static final Identifier BUTTON_HOVER_SPRITE = Identifier.withDefaultNamespace("widget/button_highlighted");
	private static final Identifier BUTTON_OFF_SPRITE = Identifier.withDefaultNamespace("widget/button_disabled");
	private static final Identifier SCROLLER_SPRITE = Identifier.withDefaultNamespace("widget/scroller");
	private static final Identifier SCROLLER_TRACK_SPRITE = Identifier.withDefaultNamespace("widget/scroller_background");
	private static final int RIGHT_BUTTON = 1;
	private static final float MOB_LOOK_OFFSET = 0.0625F;
	// The game wants every entity it draws to have an id, and this one was never in a world to be given one.
	private static final int PREVIEW_ID = -1;
	private static final Logger LOGGER = LoggerFactory.getLogger("Companion");

	private final JsonObject definition;
	private final List<JsonObject> widgets = new ArrayList<>();
	private final Map<String, String> texts = new HashMap<>();
	private final Map<String, String> tooltips = new HashMap<>();
	private final Map<String, Float> values = new HashMap<>();
	private final Map<String, Boolean> enabled = new HashMap<>();
	private final Map<String, Boolean> visible = new HashMap<>();
	private final Map<String, ItemStack> items = new HashMap<>();
	private final Map<String, ItemStack> icons = new HashMap<>();
	private final Map<String, List<Row>> rows = new HashMap<>();
	private final Map<String, Integer> scrolled = new HashMap<>();
	private final Map<String, EditBox> fields = new HashMap<>();
	private final Map<String, String> typed = new HashMap<>();
	private final Map<String, LivingEntity> mobs = new HashMap<>();
	private final Set<String> cantDraw = new HashSet<>();
	private String page = "";
	private int inventoryLeft;
	private int inventoryTop;

	private record Row(String text, ItemStack icon, boolean enabled, String tooltip) {}

	PanelScreen(ChestMenu menu, Inventory inventory, Component title, JsonObject definition) {
		super(menu, inventory, title, number(definition, "width", DEFAULT_WIDTH), number(definition, "height", DEFAULT_HEIGHT));
		this.definition = definition;
		for (JsonElement element : definition.getAsJsonArray("widgets")) {
			this.widgets.add(element.getAsJsonObject());
		}
		placeSlots(menu);
	}

	private final class Moved extends Slot {
		private final JsonObject widget;

		Moved(Container container, int slot, int x, int y, JsonObject widget) {
			super(container, slot, x, y);
			this.widget = widget;
		}

		@Override
		public boolean isActive() {
			return this.widget == null || isShown(this.widget);
		}
	}

	private static final class Hidden extends Slot {
		Hidden(Container container, int slot) {
			super(container, slot, 0, 0);
		}

		@Override
		public boolean isActive() {
			return false;
		}

		@Override
		public boolean mayPlace(ItemStack stack) {
			return false;
		}

		@Override
		public boolean mayPickup(Player player) {
			return false;
		}
	}

	private void placeSlots(ChestMenu menu) {
		int chest = menu.getRowCount() * CHEST_ROW;
		for (int index = 0; index < chest; index++) {
			Slot old = menu.slots.get(index);
			JsonObject widget = slotWidgetAt(index);
			replace(menu, index, widget == null
					? new Hidden(old.container, old.getContainerSlot())
					: new Moved(old.container, old.getContainerSlot(), number(widget, "x", 0), number(widget, "y", 0), widget));
		}
		JsonElement inventory = this.definition.get("inventory");
		boolean shown = inventory == null || inventory.isJsonObject();
		int left = shown && inventory != null ? number(inventory.getAsJsonObject(), "x", 0) : (this.imageWidth - CHEST_ROW * SLOT_SIZE) / 2 + 1;
		int top = shown && inventory != null ? number(inventory.getAsJsonObject(), "y", 0) : this.imageHeight - INVENTORY_HEIGHT;
		this.inventoryLeft = left;
		this.inventoryTop = top;
		for (int index = 0; index < (MAIN_ROWS + 1) * CHEST_ROW; index++) {
			int whole = chest + index;
			Slot old = menu.slots.get(whole);
			int row = index / CHEST_ROW;
			int x = left + (index % CHEST_ROW) * SLOT_SIZE;
			int y = top + row * SLOT_SIZE + (row == MAIN_ROWS ? HOTBAR_GAP : 0);
			replace(menu, whole, shown ? new Moved(old.container, old.getContainerSlot(), x, y, null) : new Hidden(old.container, old.getContainerSlot()));
		}
	}

	private static void replace(ChestMenu menu, int index, Slot slot) {
		slot.index = index;
		menu.slots.set(index, slot);
	}

	private JsonObject slotWidgetAt(int chestSlot) {
		for (JsonObject widget : this.widgets) {
			if (string(widget, "type").equals("slot") && number(widget, "chest_slot", -1) == chestSlot) {
				return widget;
			}
		}
		return null;
	}

	/** What the server says has changed, or everything it set if the panel is just opening. */
	void update(JsonObject state, List<ItemStack> stacks) {
		copyStrings(state, "text", this.texts);
		copyStrings(state, "tooltip", this.tooltips);
		copyFloats(state, "value", this.values);
		copyBooleans(state, "enabled", this.enabled);
		copyBooleans(state, "visible", this.visible);
		if (state.has("icons")) {
			state.getAsJsonObject("icons").asMap().forEach((id, index) -> this.icons.put(id, stacks.get(index.getAsInt())));
		}
		if (state.has("items")) {
			state.getAsJsonObject("items").asMap().forEach((id, index) -> this.items.put(id, stacks.get(index.getAsInt())));
		}
		if (state.has("rows")) {
			state.getAsJsonObject("rows").asMap().forEach((id, list) -> this.rows.put(id, readRows(list.getAsJsonArray(), stacks)));
		}
		if (state.has("page")) {
			this.page = state.get("page").getAsString();
		}
		if (state.has("typed")) {
			state.getAsJsonObject("typed").asMap().forEach((id, value) -> {
				this.typed.put(id, value.getAsString());
				EditBox box = this.fields.get(id);
				if (box != null && !box.getValue().equals(value.getAsString())) {
					box.setValue(value.getAsString());
				}
			});
		}
		applyToFields();
	}

	private static List<Row> readRows(JsonArray list, List<ItemStack> stacks) {
		List<Row> found = new ArrayList<>();
		for (JsonElement element : list) {
			JsonObject row = element.getAsJsonObject();
			found.add(new Row(string(row, "text"), row.has("icon") ? stacks.get(row.get("icon").getAsInt()) : ItemStack.EMPTY,
					!row.has("enabled") || row.get("enabled").getAsBoolean(), string(row, "tooltip")));
		}
		return found;
	}

	private void applyToFields() {
		for (JsonObject widget : this.widgets) {
			EditBox box = this.fields.get(string(widget, "id"));
			if (box != null && string(widget, "type").equals("text_field")) {
				box.visible = isShown(widget);
				box.setEditable(isEnabled(widget));
			}
		}
	}

	@Override
	protected void init() {
		super.init();
		this.titleLabelX = number(this.definition, "title_x", 8);
		this.titleLabelY = number(this.definition, "title_y", 6);
		this.fields.clear();
		for (JsonObject widget : this.widgets) {
			if (string(widget, "type").equals("text_field")) {
				String id = string(widget, "id");
				EditBox box = new EditBox(this.font, this.leftPos + number(widget, "x", 0), this.topPos + number(widget, "y", 0), number(widget, "width", 80), number(widget, "height", 16), Component.empty());
				box.setMaxLength(number(widget, "max_length", 32));
				box.setValue(this.typed.getOrDefault(id, ""));
				if (widget.has("hint")) {
					box.setHint(Component.literal(string(widget, "hint")));
				}
				box.setResponder(value -> {
					this.typed.put(id, value);
					PanelClient.typed(this.menu.containerId, id, value);
				});
				this.fields.put(id, addRenderableWidget(box));
			}
		}
		applyToFields();
	}

	// Drawing ------------------------------------------------------------------------------------------------

	@Override
	public void extractBackground(GuiGraphicsExtractor graphics, int mouseX, int mouseY, float delta) {
		super.extractBackground(graphics, mouseX, mouseY, delta);
		String background = string(this.definition, "background");
		if (!background.isEmpty()) {
			image(graphics, background, this.leftPos, this.topPos, this.imageWidth, this.imageHeight);
		} else {
			drawPanel(graphics, this.leftPos, this.topPos, this.imageWidth, this.imageHeight);
			// With no art to show where they go, slots need to be drawn.
			for (Slot slot : this.menu.slots) {
				if (slot.isActive()) {
					graphics.blitSprite(RenderPipelines.GUI_TEXTURED, SLOT_SPRITE, this.leftPos + slot.x - 1, this.topPos + slot.y - 1, SLOT_SIZE, SLOT_SIZE);
				}
			}
		}
		for (JsonObject widget : this.widgets) {
			if (isShown(widget)) {
				draw(graphics, widget, mouseX, mouseY);
			}
		}
	}

	/** The same pixels as the game's own containers, at any size. assetkit's panel_back draws the same, for art to start from. */
	private static void drawPanel(GuiGraphicsExtractor graphics, int x, int y, int width, int height) {
		int right = x + width;
		int bottom = y + height;
		graphics.fill(x + 3, y + 3, right - 3, bottom - 3, PANEL_COLOUR);
		graphics.fill(right - 3, y + 2, right - 2, y + 3, PANEL_COLOUR);
		graphics.fill(x + 2, bottom - 3, x + 3, bottom - 2, PANEL_COLOUR);
		graphics.fill(x + 2, y + 1, right - 3, y + 2, EDGE_LIGHT);
		graphics.fill(x + 1, y + 2, right - 3, y + 3, EDGE_LIGHT);
		graphics.fill(x + 1, y + 3, x + 3, bottom - 3, EDGE_LIGHT);
		graphics.fill(x + 3, y + 3, x + 4, y + 4, EDGE_LIGHT);
		graphics.fill(right - 3, y + 3, right - 1, bottom - 3, EDGE_DARK);
		graphics.fill(right - 4, bottom - 4, right - 3, bottom - 3, EDGE_DARK);
		graphics.fill(x + 3, bottom - 3, right - 1, bottom - 2, EDGE_DARK);
		graphics.fill(x + 3, bottom - 2, right - 2, bottom - 1, EDGE_DARK);
		graphics.fill(x + 2, y, right - 3, y + 1, OUTLINE);
		graphics.fill(x + 1, y + 1, x + 2, y + 2, OUTLINE);
		graphics.fill(x, y + 2, x + 1, bottom - 3, OUTLINE);
		graphics.fill(x + 1, bottom - 3, x + 2, bottom - 2, OUTLINE);
		graphics.fill(x + 2, bottom - 2, x + 3, bottom - 1, OUTLINE);
		graphics.fill(x + 3, bottom - 1, right - 2, bottom, OUTLINE);
		graphics.fill(right - 3, y + 1, right - 2, y + 2, OUTLINE);
		graphics.fill(right - 2, y + 2, right - 1, y + 3, OUTLINE);
		graphics.fill(right - 1, y + 3, right, bottom - 2, OUTLINE);
		graphics.fill(right - 2, bottom - 2, right - 1, bottom - 1, OUTLINE);
	}

	/** Pressed into the panel, like a slot of any size. */
	private static void drawSunken(GuiGraphicsExtractor graphics, int x, int y, int width, int height, int colour) {
		graphics.fill(x, y, x + width, y + height, colour);
		graphics.fill(x, y, x + width - 1, y + 1, SLOT_SHADE);
		graphics.fill(x, y, x + 1, y + height - 1, SLOT_SHADE);
		graphics.fill(x + 1, y + height - 1, x + width, y + height, EDGE_LIGHT);
		graphics.fill(x + width - 1, y + 1, x + width, y + height, EDGE_LIGHT);
	}

	private void draw(GuiGraphicsExtractor graphics, JsonObject widget, int mouseX, int mouseY) {
		int x = this.leftPos + number(widget, "x", 0);
		int y = this.topPos + number(widget, "y", 0);
		int width = number(widget, "width", 0);
		int height = number(widget, "height", 0);
		String id = string(widget, "id");
		switch (string(widget, "type")) {
			case "label" -> {
				String text = this.texts.getOrDefault(id, string(widget, "text"));
				int colour = colour(widget, "color", TEXT_ON_PANEL);
				boolean shadow = widget.has("shadow") && widget.get("shadow").getAsBoolean();
				if (width > 0) {
					int line = 0;
					for (FormattedCharSequence wrapped : this.font.split(Component.literal(text), width)) {
						graphics.text(this.font, wrapped, x, y + line++ * (TEXT_HEIGHT + 1), colour, shadow);
					}
				} else {
					graphics.text(this.font, text, x, y, colour, shadow);
				}
			}
			case "icon" -> {
				ItemStack stack = this.items.containsKey(id) ? this.items.get(id) : this.icons.getOrDefault(string(widget, "icon"), ItemStack.EMPTY);
				graphics.item(stack, x, y);
			}
			case "image" -> image(graphics, string(widget, "image"), x, y, width, height);
			case "bar" -> drawBar(graphics, widget, id, x, y, width, height);
			case "button" -> drawButton(graphics, widget, id, x, y, width, height, mouseX, mouseY);
			case "tabs" -> drawTabs(graphics, widget, x, y, mouseX, mouseY);
			case "list" -> drawList(graphics, widget, id, x, y, width, height, mouseX, mouseY);
			case "mob" -> drawMob(graphics, widget, x, y, width, height, mouseX, mouseY);
			default -> {}
		}
	}

	private void drawBar(GuiGraphicsExtractor graphics, JsonObject widget, String id, int x, int y, int width, int height) {
		float value = this.values.getOrDefault(id, widget.has("value") ? widget.get("value").getAsFloat() : 0);
		String direction = widget.has("direction") ? string(widget, "direction") : "right";
		boolean sideways = direction.equals("right") || direction.equals("left");
		String image = string(widget, "image");
		if (image.isEmpty()) {
			// Inside a frame, the way a progress bar in a container sits in the panel.
			drawSunken(graphics, x, y, width, height, colour(widget, "back_color", SLOT_COLOUR));
			x++;
			y++;
			width -= 2;
			height -= 2;
		}
		int filled = Math.round((sideways ? width : height) * value);
		int left = direction.equals("left") ? x + width - filled : x;
		int top = direction.equals("up") ? y + height - filled : y;
		int shownWidth = sideways ? filled : width;
		int shownHeight = sideways ? height : filled;
		if (image.isEmpty()) {
			graphics.fill(left, top, left + shownWidth, top + shownHeight, colour(widget, "color", BAR_COLOUR));
			return;
		}
		Identifier texture = Identifier.tryParse(image);
		if (texture != null && filled > 0) {
			graphics.blit(RenderPipelines.GUI_TEXTURED, texture, left, top, left - x, top - y, shownWidth, shownHeight, width, height);
		}
	}

	private void drawButton(GuiGraphicsExtractor graphics, JsonObject widget, String id, int x, int y, int width, int height, int mouseX, int mouseY) {
		boolean on = isEnabled(widget);
		boolean hovered = on && inside(mouseX, mouseY, x, y, width, height);
		String image = string(widget, on ? hovered ? "hover_image" : "image" : "disabled_image");
		if (image.isEmpty()) {
			image = string(widget, "image");
		}
		if (!image.isEmpty()) {
			image(graphics, image, x, y, width, height);
		} else {
			graphics.blitSprite(RenderPipelines.GUI_TEXTURED, !on ? BUTTON_OFF_SPRITE : hovered ? BUTTON_HOVER_SPRITE : BUTTON_SPRITE, x, y, width, height);
		}
		String icon = string(widget, "icon");
		String text = this.texts.getOrDefault(id, string(widget, "text"));
		if (!icon.isEmpty() && text.isEmpty()) {
			graphics.item(this.icons.getOrDefault(icon, ItemStack.EMPTY), x + (width - ICON_SIZE) / 2, y + (height - ICON_SIZE) / 2);
		}
		if (!text.isEmpty()) {
			graphics.centeredText(this.font, text, x + width / 2, y + (height - TEXT_HEIGHT) / 2 + 1, on ? TEXT_ON_BUTTON : TEXT_OFF);
		}
	}

	private void drawTabs(GuiGraphicsExtractor graphics, JsonObject widget, int x, int y, int mouseX, int mouseY) {
		int left = x;
		for (JsonElement element : widget.getAsJsonArray("tabs")) {
			JsonObject tab = element.getAsJsonObject();
			int width = tabWidth(tab);
			boolean current = string(tab, "id").equals(this.page);
			boolean hovered = inside(mouseX, mouseY, left, y, width, TAB_HEIGHT);
			drawTab(graphics, left, y, width, current, hovered);
			// Dark text on the light tab that's open would look smudged with a shadow.
			graphics.text(this.font, string(tab, "text"), left + (width - this.font.width(string(tab, "text"))) / 2, y + (TAB_HEIGHT - TEXT_HEIGHT) / 2 + 1, current ? TEXT_ON_PANEL : TEXT_ON_BUTTON, !current);
			left += width + 1;
		}
	}

	/** Lit from the top left with a black edge, like everything in a container, and the open one is part of the panel. */
	private static void drawTab(GuiGraphicsExtractor graphics, int x, int y, int width, boolean open, boolean hovered) {
		int right = x + width;
		int bottom = y + TAB_HEIGHT;
		graphics.fill(x + 1, y + 1, right - 1, bottom, open ? PANEL_COLOUR : hovered ? TAB_HOVER : SLOT_COLOUR);
		graphics.fill(x + 1, y, right - 1, y + 1, OUTLINE);
		graphics.fill(x, y + 1, x + 1, bottom, OUTLINE);
		graphics.fill(right - 1, y + 1, right, bottom, OUTLINE);
		graphics.fill(x + 1, y + 1, right - 1, y + 2, EDGE_LIGHT);
		graphics.fill(x + 1, y + 1, x + 2, bottom, EDGE_LIGHT);
		graphics.fill(right - 2, y + 2, right - 1, bottom, EDGE_DARK);
		if (!open) {
			graphics.fill(x, bottom - 1, right, bottom, OUTLINE);
		}
	}

	private int tabWidth(JsonObject tab) {
		return this.font.width(string(tab, "text")) + TAB_PADDING;
	}

	private void drawList(GuiGraphicsExtractor graphics, JsonObject widget, String id, int x, int y, int width, int height, int mouseX, int mouseY) {
		List<Row> list = this.rows.getOrDefault(id, List.of());
		int rowHeight = number(widget, "row_height", ROW_HEIGHT);
		int offset = scrollOf(id, list.size(), rowHeight, height);
		int total = list.size() * rowHeight;
		boolean scrolls = total > height;
		int rowWidth = scrolls ? width - SCROLLER_WIDTH : width;
		drawSunken(graphics, x, y, width, height, colour(widget, "back_color", SLOT_COLOUR));
		graphics.enableScissor(x, y, x + width, y + height);
		for (int index = 0; index < list.size(); index++) {
			Row row = list.get(index);
			int top = y + index * rowHeight - offset;
			if (top + rowHeight <= y || top >= y + height) {
				continue;
			}
			// Each row is a button, the way a villager's trades are.
			boolean hovered = row.enabled() && inside(mouseX, mouseY, x, y, width, height) && inside(mouseX, mouseY, x, top, rowWidth, rowHeight);
			graphics.blitSprite(RenderPipelines.GUI_TEXTURED, !row.enabled() ? BUTTON_OFF_SPRITE : hovered ? BUTTON_HOVER_SPRITE : BUTTON_SPRITE, x, top, rowWidth, rowHeight);
			int textLeft = x + 4;
			if (!row.icon().isEmpty()) {
				graphics.item(row.icon(), x + 2, top + (rowHeight - ICON_SIZE) / 2);
				textLeft = x + ICON_SIZE + 4;
			}
			graphics.text(this.font, row.text(), textLeft, top + (rowHeight - TEXT_HEIGHT) / 2 + 1, row.enabled() ? TEXT_ON_BUTTON : TEXT_OFF, true);
		}
		graphics.disableScissor();
		if (scrolls) {
			int barHeight = Math.max(SMALLEST_SCROLLER, height * height / total);
			int barTop = y + (height - barHeight) * offset / (total - height);
			graphics.blitSprite(RenderPipelines.GUI_TEXTURED, SCROLLER_TRACK_SPRITE, x + width - SCROLLER_WIDTH, y, SCROLLER_WIDTH, height);
			graphics.blitSprite(RenderPipelines.GUI_TEXTURED, SCROLLER_SPRITE, x + width - SCROLLER_WIDTH, barTop, SCROLLER_WIDTH, barHeight);
		}
	}

	private int scrollOf(String id, int rowCount, int rowHeight, int height) {
		int most = Math.max(0, rowCount * rowHeight - height);
		int kept = Math.clamp(this.scrolled.getOrDefault(id, 0), 0, most);
		this.scrolled.put(id, kept);
		return kept;
	}

	private void drawMob(GuiGraphicsExtractor graphics, JsonObject widget, int x, int y, int width, int height, int mouseX, int mouseY) {
		String portrait = string(widget, "portrait");
		if (!portrait.isEmpty()) {
			image(graphics, portrait, x, y, width, height);
			return;
		}
		String name = string(widget, "mob");
		LivingEntity mob = this.cantDraw.contains(name) ? null : this.mobs.computeIfAbsent(name, this::makeMob);
		if (mob == null) {
			return;
		}
		try {
			InventoryScreen.extractEntityInInventoryFollowsMouse(graphics, x, y, x + width, y + height, number(widget, "size", height / 2), MOB_LOOK_OFFSET, mouseX, mouseY, mob);
		} catch (RuntimeException error) {
			// Some mobs aren't made to be drawn out of a world, and that shouldn't take the whole game down.
			LOGGER.warn("Can't draw {} on a panel", name, error);
			this.cantDraw.add(name);
		}
	}

	private LivingEntity makeMob(String name) {
		Identifier id = Identifier.tryParse(name);
		if (id == null || this.minecraft == null || this.minecraft.level == null) {
			return null;
		}
		// A mob of this world isn't known to the game here, which is why one of those needs a portrait.
		EntityType<?> type = BuiltInRegistries.ENTITY_TYPE.getOptional(id).orElse(null);
		Entity made = type == null ? null : type.create(this.minecraft.level, EntitySpawnReason.LOAD);
		if (!(made instanceof LivingEntity living)) {
			return null;
		}
		living.setId(PREVIEW_ID);
		return living;
	}

	private static void image(GuiGraphicsExtractor graphics, String name, int x, int y, int width, int height) {
		Identifier texture = Identifier.tryParse(name);
		if (texture != null) {
			graphics.blit(RenderPipelines.GUI_TEXTURED, texture, x, y, 0, 0, width, height, width, height);
		}
	}

	@Override
	protected void extractLabels(GuiGraphicsExtractor graphics, int mouseX, int mouseY) {
		if (!string(this.definition, "title").isEmpty()) {
			graphics.text(this.font, this.title, this.titleLabelX, this.titleLabelY, TEXT_ON_PANEL, false);
		}
		JsonElement inventory = this.definition.get("inventory");
		if (inventory == null || inventory.isJsonObject()) {
			graphics.text(this.font, this.playerInventoryTitle, this.inventoryLeft, this.inventoryTop - INVENTORY_LABEL_ABOVE, TEXT_ON_PANEL, false);
		}
	}

	@Override
	protected void extractTooltip(GuiGraphicsExtractor graphics, int mouseX, int mouseY) {
		super.extractTooltip(graphics, mouseX, mouseY);
		String tip = tooltipAt(mouseX, mouseY);
		if (!tip.isEmpty()) {
			graphics.setTooltipForNextFrame(this.font, Component.literal(tip), mouseX, mouseY);
		}
	}

	private String tooltipAt(int mouseX, int mouseY) {
		for (JsonObject widget : this.widgets) {
			if (!isShown(widget)) {
				continue;
			}
			String id = string(widget, "id");
			int x = this.leftPos + number(widget, "x", 0);
			int y = this.topPos + number(widget, "y", 0);
			int width = number(widget, "width", ICON_SIZE);
			int height = number(widget, "height", ICON_SIZE);
			if (!inside(mouseX, mouseY, x, y, width, height)) {
				continue;
			}
			if (string(widget, "type").equals("list")) {
				int row = rowAt(widget, id, y, height, mouseY);
				List<Row> list = this.rows.getOrDefault(id, List.of());
				return row >= 0 && row < list.size() ? list.get(row).tooltip() : "";
			}
			if (string(widget, "type").equals("icon") && !this.tooltips.containsKey(id) && !widget.has("tooltip")) {
				ItemStack stack = this.items.containsKey(id) ? this.items.get(id) : this.icons.getOrDefault(string(widget, "icon"), ItemStack.EMPTY);
				return stack.isEmpty() ? "" : stack.getHoverName().getString();
			}
			String tip = this.tooltips.getOrDefault(id, string(widget, "tooltip"));
			if (!tip.isEmpty()) {
				return tip;
			}
		}
		return "";
	}

	private int rowAt(JsonObject widget, String id, int y, int height, double mouseY) {
		int rowHeight = number(widget, "row_height", ROW_HEIGHT);
		int offset = scrollOf(id, this.rows.getOrDefault(id, List.of()).size(), rowHeight, height);
		return (int) Math.floor((mouseY - y + offset) / rowHeight);
	}

	// Input --------------------------------------------------------------------------------------------------

	@Override
	public boolean mouseClicked(MouseButtonEvent event, boolean doubled) {
		if (click(event)) {
			return true;
		}
		return super.mouseClicked(event, doubled);
	}

	private boolean click(MouseButtonEvent event) {
		double mouseX = event.x();
		double mouseY = event.y();
		for (JsonObject widget : this.widgets) {
			if (!isShown(widget)) {
				continue;
			}
			int x = this.leftPos + number(widget, "x", 0);
			int y = this.topPos + number(widget, "y", 0);
			int width = number(widget, "width", 0);
			int height = number(widget, "height", 0);
			String id = string(widget, "id");
			int first = number(widget, "chest_slot", -1);
			switch (string(widget, "type")) {
				case "button" -> {
					if (inside(mouseX, mouseY, x, y, width, height) && isEnabled(widget)) {
						press(first, event);
						return true;
					}
				}
				case "tabs" -> {
					int left = x;
					int index = 0;
					for (JsonElement element : widget.getAsJsonArray("tabs")) {
						int tabWidth = tabWidth(element.getAsJsonObject());
						if (inside(mouseX, mouseY, left, y, tabWidth, TAB_HEIGHT)) {
							press(first + index, event);
							return true;
						}
						left += tabWidth + 1;
						index++;
					}
				}
				case "list" -> {
					if (inside(mouseX, mouseY, x, y, width, height)) {
						int row = rowAt(widget, id, y, height, mouseY);
						List<Row> list = this.rows.getOrDefault(id, List.of());
						if (row >= 0 && row < list.size() && list.get(row).enabled()) {
							press(first + row, event);
						}
						return true;
					}
				}
				default -> {}
			}
		}
		return false;
	}

	/** The very same click a plain chest would send for this picture. */
	private void press(int chestSlot, MouseButtonEvent event) {
		boolean shift = (event.modifiers() & InputConstants.MOD_SHIFT) != 0;
		this.minecraft.gameMode.handleContainerInput(this.menu.containerId, chestSlot, event.button() == RIGHT_BUTTON ? 1 : 0, shift ? ContainerInput.QUICK_MOVE : ContainerInput.PICKUP, this.minecraft.player);
		this.minecraft.getSoundManager().play(SimpleSoundInstance.forUI(SoundEvents.UI_BUTTON_CLICK, 1.0F));
	}

	@Override
	public boolean mouseScrolled(double mouseX, double mouseY, double scrollX, double scrollY) {
		for (JsonObject widget : this.widgets) {
			if (string(widget, "type").equals("list") && isShown(widget)
					&& inside(mouseX, mouseY, this.leftPos + number(widget, "x", 0), this.topPos + number(widget, "y", 0), number(widget, "width", 0), number(widget, "height", 0))) {
				String id = string(widget, "id");
				this.scrolled.put(id, this.scrolled.getOrDefault(id, 0) - (int) (scrollY * number(widget, "row_height", ROW_HEIGHT)));
				return true;
			}
		}
		return super.mouseScrolled(mouseX, mouseY, scrollX, scrollY);
	}

	/** While a field has the keyboard, everything typed goes to it, so a letter doesn't close the screen. Escape still does. */
	@Override
	public boolean keyPressed(KeyEvent event) {
		for (EditBox box : this.fields.values()) {
			if (box.isFocused() && box.visible) {
				if (event.key() == InputConstants.KEY_ESCAPE) {
					this.minecraft.player.closeContainer();
					return true;
				}
				return box.keyPressed(event) || box.canConsumeInput() || super.keyPressed(event);
			}
		}
		return super.keyPressed(event);
	}

	// Reading the description --------------------------------------------------------------------------------

	private boolean isShown(JsonObject widget) {
		String id = string(widget, "id");
		String on = string(widget, "page");
		return this.visible.getOrDefault(id, true) && (on.isEmpty() || on.equals(this.page));
	}

	private boolean isEnabled(JsonObject widget) {
		return this.enabled.getOrDefault(string(widget, "id"), !widget.has("enabled") || widget.get("enabled").getAsBoolean());
	}

	private static boolean inside(double mouseX, double mouseY, int x, int y, int width, int height) {
		return mouseX >= x && mouseX < x + width && mouseY >= y && mouseY < y + height;
	}

	private static String string(JsonObject json, String field) {
		return json.has(field) ? json.get(field).getAsString() : "";
	}

	private static int number(JsonObject json, String field, int otherwise) {
		return json.has(field) ? json.get(field).getAsInt() : otherwise;
	}

	private static int colour(JsonObject json, String field, int otherwise) {
		String text = string(json, field);
		return text.startsWith("#") ? 0xFF000000 | Integer.parseInt(text.substring(1), 16) : otherwise;
	}

	private static void copyStrings(JsonObject state, String kind, Map<String, String> into) {
		if (state.has(kind)) {
			state.getAsJsonObject(kind).asMap().forEach((id, value) -> into.put(id, value.getAsString()));
		}
	}

	private static void copyFloats(JsonObject state, String kind, Map<String, Float> into) {
		if (state.has(kind)) {
			state.getAsJsonObject(kind).asMap().forEach((id, value) -> into.put(id, value.getAsFloat()));
		}
	}

	private static void copyBooleans(JsonObject state, String kind, Map<String, Boolean> into) {
		if (state.has(kind)) {
			state.getAsJsonObject(kind).asMap().forEach((id, value) -> into.put(id, value.getAsBoolean()));
		}
	}
}
