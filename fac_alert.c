#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <netdb.h>
#include <stdint.h>
#include <stdbool.h>
#include <ctype.h>
#include <getopt.h>
#include <assert.h>
#include <errno.h>
#include <signal.h>

#include <asn1/v2x_eu_asn.h>
#include <asn1/v2x_us_asn.h>
#include <asn1/v2x_cn_asn.h>

#include <cms_v2x/api.h>
#include <cms_v2x/wsmp.h>

#include <asn1defs.h>

#define PORT 8080
#define BUFFER_SIZE 16384
#define RECONNECT_DELAY_SEC 2

static const cms_psid_t PSID = 0x87UL; /* Non p-encoded PSID */

void json_to_uper(const char *json_buf, cms_session_t session, cms_wsmp_send_data_t send_hdr);
static bool send_message(uint8_t *msg_payload, size_t data_len, cms_session_t session, cms_wsmp_send_data_t send_hdr);

uint8_t hex_char_to_uint8_t(char c) {
    if (c >= '0' && c <= '9') {
        return c - '0';
    } else if (c >= 'A' && c <= 'F') {
        return c - 'A' + 10;
    } else if (c >= 'a' && c <= 'f') {
        return c - 'a' + 10;
    }
    return 0;
}

void hex_to_uint8_t_array(const char *hex_str, uint8_t *output_array) {
    size_t length = strlen(hex_str);

    if (length % 2 != 0) {
        printf("Invalid hex string length\n");
        return;
    }

    for (size_t i = 0; i < length; i += 2) {
        output_array[i / 2] = (hex_char_to_uint8_t(hex_str[i]) << 4) | hex_char_to_uint8_t(hex_str[i + 1]);
    }
}

void binary_to_hex_string(const uint8_t *binary_data, size_t data_len, char *hex_str) {
    for (size_t i = 0; i < data_len; i++) {
        sprintf(&hex_str[i * 2], "%02X", binary_data[i]);
    }
}

int extract_json_block(const char *input, const char *key, char *output, size_t max_len) {
    char search[64];
    snprintf(search, sizeof(search), "\"%s\"", key);

    char *key_start = strstr(input, search);
    if (!key_start) return -1;

    char *colon = strchr(key_start, ':');
    if (!colon) return -1;

    char *start = colon + 1;
    while (*start == ' ' || *start == '\t' || *start == '\n') start++;

    if (*start != '{') return -1;

    int brace_count = 1;
    char *ptr = start + 1;
    while (*ptr && brace_count > 0) {
        if (*ptr == '{') brace_count++;
        else if (*ptr == '}') brace_count--;
        ptr++;
    }

    if (brace_count != 0) return -1;

    size_t len = ptr - start;
    if (len >= max_len) return -1;

    strncpy(output, start, len);
    output[len] = '\0';
    return 0;
}

typedef struct {
    const char *key;
    const ASN1CType *asn_type;
    int message_id;
} message_mapping_t;

void json_to_uper(const char *json_buf, cms_session_t session, cms_wsmp_send_data_t send_hdr)
{
    bool error = false;
    void* c_struct = NULL;
    char extracted_json[16384];

    /* All messages are now encoded as MessageFrame.
     * The Python script sends JSON like: { "bsm": { "messageId": 20, "value": { "coreData": {...} } } }
     * We extract the inner MessageFrame JSON and encode it as US_MessageFrame. */
    const char *keys[] = { "bsm", "mapData", "spat", "rsa", "tim", "psm", NULL };

    const char *found_key = NULL;

    for (int i = 0; keys[i] != NULL; i++) {
        if (extract_json_block(json_buf, keys[i], extracted_json, sizeof(extracted_json)) == 0) {
            found_key = keys[i];
            break;
        }
    }

    if (found_key == NULL) {
        return;
    }

    uint32_t json_len = (uint32_t)strlen(extracted_json);

    fprintf(stderr,
        "JSON input (%s):\n"
        "%s\n"
        "--- End of JSON input\n\n",
        found_key, extracted_json);

    if(!error) {
        ASN1Error err = {0};
        asn1_ssize_t ret = asn1_jer_decode((void**)&c_struct,
                                        asn1_type_US_MessageFrame,
                                        (uint8_t*)extracted_json,
                                        json_len,
                                        &err);
        if((ret < 0) || (c_struct == NULL)) {
            fprintf(stderr, "Decoding error for %s: %s\n", found_key, err.msg);
            error = true;
        }
    }

    if(!error) {
        uint8_t* uper_ptr = NULL;
        ASN1Error err = {0};
        int ret = asn1_uper_encode2(&uper_ptr, asn1_type_US_MessageFrame, c_struct, &err);
        if((ret < 0) || (uper_ptr == NULL)) {
            fprintf(stderr, "Encoding error for %s: %s\n", found_key, err.msg);
            error = true;
        } else {
            fprintf(stderr, "Encoded data (%s):\n", found_key);
            for(int i = 0; i < ret; i++) {
                printf("%02X", uper_ptr[i]);
            }
            printf("\n");
            fflush(stdout);
            fprintf(stderr, "--- End of encoded data\n\n");

            char hex_str[ret * 2 + 1];
            binary_to_hex_string(uper_ptr, ret, hex_str);

            size_t hex_str_len = strlen(hex_str);
            size_t byte_array_len = hex_str_len / 2;
            uint8_t byte_array[byte_array_len];
            
            hex_to_uint8_t_array(hex_str, byte_array);

            send_message(byte_array, ret, session, send_hdr);
        }

        if(uper_ptr != NULL) {
            asn1_free(uper_ptr);
        }
    }

    if(c_struct != NULL) {
        asn1_free_value(asn1_type_US_MessageFrame, c_struct);
    }
}

bool send_message(uint8_t *msg_payload, size_t data_len, cms_session_t session, cms_wsmp_send_data_t send_hdr) {
    bool error = false;
    
    /* Create a buffer view as a handle to the actual payload buffer */
    cms_buffer_view_t msg = {
        .data = msg_payload,
        .length = data_len
    };

    printf("Hex of encoded data:\n");
    for (size_t i = 0; i < data_len; i++) {
        printf("0x%02X ", msg_payload[i]);
        if ((i + 1) % 16 == 0) {
            printf("\n");
        }
    }
    printf("\n");
    fflush(stdout);
    fprintf(stderr, "--- End of hex of encoded data\n\n");

    /* Send the prepared WSMP message */
    error = error || cms_wsmp_send(&session, &send_hdr, msg, NULL);
    if(error) {
        printf("Unable to send WSMP message\n");
    } else {
        printf("WSMP message sent\n");
    }
    fflush(stdout);

    return error;
}

int main(int argc, char *argv[]) {
    // Usage: ./fac_alert <CARLA_SERVER_HOST_1> [CARLA_SERVER_HOST_2] ...
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <CARLA_SERVER_HOST_1> [CARLA_SERVER_HOST_2] ...\n", argv[0]);
        fprintf(stderr, "Example: %s 192.168.0.56 192.168.0.246\n", argv[0]);
        return 1;
    }
    
    int num_servers = argc - 1;
    char **server_hosts = &argv[1];
    int current_server_idx = 0;

    // Ignore SIGPIPE to prevent the app from crashing if it writes to a closed socket
    signal(SIGPIPE, SIG_IGN);

    // --- CMS V2X Session Setup ---
    cms_session_t session = cms_get_session();
    bool error = cms_api_connect_easy(&session, "127.0.0.1");
    if (error) {
        fprintf(stderr, "Failed to connect to V2X Stack API\n");
    }

    static const uint8_t BROADCAST_ADDR[CMS_MAC_ADDRESS_LENGTH] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

    /* Create send header */
    cms_wsmp_send_data_t send_hdr = {0};

    send_hdr.radio.datarate = 0;
    memcpy(send_hdr.radio.dest_address, BROADCAST_ADDR, CMS_MAC_ADDRESS_LENGTH);
    send_hdr.radio.expiry_time = 0;
    send_hdr.radio.interface_id = 1; // Use C-V2X interface (qc9150)
    send_hdr.radio.sps_index = 0;
    send_hdr.radio.tx_power = 0;
    send_hdr.radio.user_prio = 0;

    send_hdr.wsmp_hdr.channel_id = false;
    send_hdr.wsmp_hdr.datarate = false;
    send_hdr.wsmp_hdr.psid = PSID;
    send_hdr.wsmp_hdr.tx_power = false;

    send_hdr.security.sign_info.psid = PSID;
    // Send as UNSECURED so the OBU receives it without dropping due to cert mismatch
    send_hdr.security.sign_info.sign_method = CMS_SIGN_METH_NONE; 
    send_hdr.security.payload_type = CMS_SEC_DOT2_TX_PAYLOAD_TYPE_EXT_DOT2_DATA;

    // --- Connection State Variables (IPv6 dual-stack) ---
    int sock_fd = -1;
    char buffer[BUFFER_SIZE];

    char port_str[8];
    snprintf(port_str, sizeof(port_str), "%d", PORT);

    while (1) {
        // 1. Check if we need to establish a connection
        if (sock_fd < 0) {
            const char *target_host = server_hosts[current_server_idx];
            
            struct addrinfo hints, *server_info = NULL;
            memset(&hints, 0, sizeof(hints));
            hints.ai_family = AF_UNSPEC;
            hints.ai_socktype = SOCK_STREAM;
            hints.ai_flags = 0;

            int gai_ret = getaddrinfo(target_host, port_str, &hints, &server_info);
            if (gai_ret != 0) {
                fprintf(stderr, "Failed to resolve '%s': %s\n", target_host, gai_strerror(gai_ret));
                // Try next server on next loop
                current_server_idx = (current_server_idx + 1) % num_servers;
                sleep(RECONNECT_DELAY_SEC);
                continue;
            }

            sock_fd = socket(server_info->ai_family, server_info->ai_socktype, server_info->ai_protocol);
            if (sock_fd < 0) {
                perror("Socket creation failed");
                freeaddrinfo(server_info);
                sleep(RECONNECT_DELAY_SEC);
                continue;
            }

            printf("Attempting to connect to server %s:%d...\n", target_host, PORT);
            if (connect(sock_fd, server_info->ai_addr, server_info->ai_addrlen) < 0) {
                fprintf(stderr, "Connection failed to %s (%s). Retrying...\n", target_host, strerror(errno));
                close(sock_fd);
                sock_fd = -1;
                freeaddrinfo(server_info);
                
                // Switch to the next server
                current_server_idx = (current_server_idx + 1) % num_servers;
                sleep(RECONNECT_DELAY_SEC);
                continue;
            }
            
            printf("Connected successfully to %s!\n", target_host);
            freeaddrinfo(server_info);
        }

        // 2. Data Reception Loop
        int partial_len = 0;
        ssize_t bytes_read;
        
        // This inner loop runs as long as the connection is healthy
        while (1) {
            bytes_read = recv(sock_fd, buffer + partial_len, BUFFER_SIZE - partial_len - 1, 0);

            if (bytes_read > 0) {
                buffer[partial_len + bytes_read] = '\0';
                char *start = buffer;
                char *end;

                // Process all complete lines (delimited by \n)
                while ((end = strchr(start, '\n')) != NULL) {
                    *end = '\0';
                    
                    // Trigger V2X processing logic
                    json_to_uper(start, session, send_hdr);

                    start = end + 1;
                }

                // Move remaining partial data to the start of the buffer
                partial_len = strlen(start);
                memmove(buffer, start, partial_len);

                if (partial_len >= BUFFER_SIZE - 1) {
                    fprintf(stderr, "Buffer overflow risk, clearing partial data.\n");
                    partial_len = 0;
                }
            } 
            else if (bytes_read == 0) {
                printf("Server closed the connection.\n");
                break; // Exit inner loop to trigger reconnect
            } 
            else {
                if (errno == EINTR) continue;
                perror("Recv error");
                break; // Exit inner loop to trigger reconnect
            }
        }

        // 3. Cleanup before reconnecting
        close(sock_fd);
        sock_fd = -1;
        printf("Reconnecting in %d seconds...\n", RECONNECT_DELAY_SEC);
        current_server_idx = (current_server_idx + 1) % num_servers; // switch to next on disconnect
        sleep(RECONNECT_DELAY_SEC);
    }

    /* Cleanup V2X (Unreachable in this infinite loop) */
    cms_api_disconnect(&session);
    cms_api_clean();
    return 0;
}
