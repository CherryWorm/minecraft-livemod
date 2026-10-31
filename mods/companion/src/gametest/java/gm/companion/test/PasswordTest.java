package gm.companion.test;

import com.mojang.blaze3d.platform.InputConstants;
import net.fabricmc.fabric.api.client.gametest.v1.FabricClientGameTest;
import net.fabricmc.fabric.api.client.gametest.v1.context.ClientGameTestContext;
import net.minecraft.client.gui.components.AbstractWidget;
import net.minecraft.client.gui.components.Button;
import net.minecraft.client.gui.components.EditBox;
import net.minecraft.client.gui.components.events.ContainerEventHandler;
import net.minecraft.client.gui.components.events.GuiEventListener;
import net.minecraft.client.gui.screens.ConnectScreen;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.client.gui.screens.TitleScreen;
import net.minecraft.client.gui.screens.dialog.DialogScreen;
import net.minecraft.client.multiplayer.ServerData;
import net.minecraft.client.multiplayer.resolver.ServerAddress;
import net.minecraft.network.chat.Component;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.function.Predicate;

/**
 * Answers the server's password dialog the way a person does: clicks the box, types, clicks the button. Lines starting
 * [M13] are read by broker/tests/m13_test.py.
 */
public final class PasswordTest implements FabricClientGameTest {
	private static final Logger LOGGER = LoggerFactory.getLogger("CompanionTest");
	private static final int TICKS_PER_MINUTE = 20 * 60;
	private static final int SETTLE_TICKS = 20;
	private static final int LOGIN_RATE_LIMIT_TICKS = 100;

	@Override
	public void runTest(ClientGameTestContext context) {
		if (!"password".equals(System.getenv("CLIENT_TEST"))) {
			return;
		}
		connect(context);
		context.waitFor(client -> client.gui.screen() instanceof DialogScreen, 5 * TICKS_PER_MINUTE);
		context.waitTicks(SETTLE_TICKS);
		context.takeScreenshot("m13_asked");
		boolean inWorld = context.computeOnClient(client -> client.level != null);
		LOGGER.info("[M13] asked, in the world already: {}", inWorld);

		Screen first = context.computeOnClient(client -> client.gui.screen());
		answer(context, "certainly not it");
		context.waitFor(client -> client.gui.screen() instanceof DialogScreen && client.gui.screen() != first, TICKS_PER_MINUTE);
		context.waitTicks(SETTLE_TICKS);
		context.takeScreenshot("m13_wrong");
		LOGGER.info("[M13] asked again after a wrong answer");

		answer(context, System.getenv("LIVINGMOD_TEST_PASSWORD"));
		context.waitFor(client -> client.level != null && client.player != null, 5 * TICKS_PER_MINUTE);
		context.waitFor(client -> client.gui.screen() == null, 2 * TICKS_PER_MINUTE);
		context.waitTicks(SETTLE_TICKS);
		context.takeScreenshot("m13_joined");
		LOGGER.info("[M13] joined");
		leave(context);

		context.waitTicks(LOGIN_RATE_LIMIT_TICKS);
		connect(context);
		context.waitFor(client -> client.level != null || client.gui.screen() instanceof DialogScreen, 5 * TICKS_PER_MINUTE);
		boolean asked = context.computeOnClient(client -> client.gui.screen() instanceof DialogScreen);
		LOGGER.info("[M13] second join asked: {}", asked);
		context.waitFor(client -> client.gui.screen() == null, 2 * TICKS_PER_MINUTE);
		leave(context);
		LOGGER.info("[M13] finished");
	}

	private static void connect(ClientGameTestContext context) {
		String address = System.getenv().getOrDefault("LIVINGMOD_SERVER", "localhost:25565");
		context.runOnClient(client -> {
			ServerData data = new ServerData("test", address, ServerData.Type.OTHER);
			data.setResourcePackStatus(ServerData.ServerPackStatus.ENABLED);
			ConnectScreen.startConnecting(new TitleScreen(), client, ServerAddress.parseString(address), data, false, null);
		});
	}

	private static void leave(ClientGameTestContext context) {
		// Closing the screens alone leaves the connection open, and the proxy then turns the next join away as a duplicate.
		context.runOnClient(client -> {
			client.getConnection().getConnection().disconnect(Component.literal("Leaving"));
			client.disconnect(new TitleScreen(), false);
		});
		context.waitFor(client -> client.level == null && client.gui.screen() instanceof TitleScreen, TICKS_PER_MINUTE);
	}

	private static void answer(ClientGameTestContext context, String text) {
		click(context, widget -> widget instanceof EditBox);
		context.getInput().typeChars(text);
		context.waitTicks(2);
		click(context, widget -> widget instanceof Button button && "Enter".equals(button.getMessage().getString()));
	}

	private static void click(ClientGameTestContext context, Predicate<AbstractWidget> wanted) {
		double[] at = context.computeOnClient(client -> {
			AbstractWidget widget = find(client.gui.screen(), wanted);
			double scale = client.getWindow().getGuiScale();
			return new double[] {(widget.getX() + widget.getWidth() / 2.0) * scale, (widget.getY() + widget.getHeight() / 2.0) * scale};
		});
		context.getInput().setCursorPos(at[0], at[1]);
		context.getInput().pressMouse(InputConstants.MOUSE_BUTTON_LEFT);
		context.waitTicks(2);
	}

	private static AbstractWidget find(ContainerEventHandler parent, Predicate<AbstractWidget> wanted) {
		for (GuiEventListener child : parent.children()) {
			if (child instanceof AbstractWidget widget && wanted.test(widget)) {
				return widget;
			}
			if (child instanceof ContainerEventHandler container) {
				AbstractWidget found = find(container, wanted);
				if (found != null) {
					return found;
				}
			}
		}
		return null;
	}
}
